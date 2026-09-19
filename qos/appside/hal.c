/* hal.c (qosapp) -- the app image's HAL: every obligation the runtime
 * has (hal_putc, the wfi/ipi/timer doorbells, ctx fabrication) and
 * every fpr_g_ device capability the image exports (device, the
 * register tier, net) dispatches through the qos_hal_t table the boot
 * record delivered.  This file plus entry.c is the whole platform
 * surface of a QOS Portable app: no libc, no syscalls, no link-time
 * binding to the host -- "the HAL is a table delivered as a C pointer,
 * called like regular C functions" (the bootstrap design), and the
 * safety mechanisms live in the FPRISC layer above, not here.
 */
#include "fpr.h"
#include "qos_abi.h"

extern const qos_hal_t *qos_hal; /* entry.c installs it first thing */

/* ---- the hal_* obligations (actors.c / runtime.c contract) ---------- */
void hal_putc(char c) { qos_hal->putc(c); }
/* actors.c's stack guard: this image cannot protect memory, its host can */
void hal_stack_guard(void *lo, uw size) { qos_hal->stack_guard(lo, size); }
void hal_stack_unguard(void *lo, uw size) { qos_hal->stack_unguard(lo, size); }
void hal_heap_release(void *p, uw bytes) { qos_hal->heap_release(p, bytes); }
/* an app never boots a machine: its heap is the arena the boot record hands
 * it (entry.c), so the runtime's own boot path is not reachable here */
void hal_heap_span(char **lo, char **hi, char **span_hi) {
  (void)lo; (void)hi; (void)span_hi;
  fpr_cpanic("hal_heap_span: an app's heap comes from the boot record");
}
void hal_poweroff(int code) { qos_hal->poweroff(code); }
void fpr_park(void) {
  for (;;) qos_hal->wfi();
}

void hal_wfi_enable(void) {}
void hal_wfi(void) { qos_hal->wfi(); } /* poll pace; rings re-checked after */
/* the CLINT model's mtime (10 MHz ticks, net_raw.c's CLINT_MTIME): the
 * clock the parked sleep (actors.c) and the timer service read */
uint64_t hal_mtime(void) { return qos_hal->mmio_read(0x2000u + 49144u, 8); }
void hal_ipi_send(uw hart) { (void)hart; } /* single-hart image */
void hal_ipi_clear(uw hart) { (void)hart; }
void hal_timer_park(uw hart) { (void)hart; }
void hal_timer_arm(uw hart, uw ticks) { (void)hart; (void)ticks; }

/* ---- first-activation contexts for ctx_*.S ------------------------
 * Same rule as posix/hal.c: on x86-64 the fabricated entry state must
 * look like post-call (entry %rsp == 8 mod 16) so that gcc's 16-byte
 * spills inside the trampoline are aligned.  AArch64 and RISC-V do not
 * need the bias. */
void fpr_ctx_fabricate(uw *ctx, void (*entry)(void), uw stack_top16,
                       fpr_hart_t *owner) {
  (void)owner; /* the hart pointer is the plain global, not a ctx slot */
  ctx[0] = (uw)(uintptr_t)entry;
#if defined(__x86_64__)
  ctx[1] = stack_top16 - 8;
#else
  ctx[1] = stack_top16;
#endif
}

/* ---- the register tier (stubs.c's mkreg handlers, table-backed) ----- */
static V mkreg(V dev, V off, uint32_t width) {
  if (ISINT(dev) || TID(dev) != T_DEVICE) fpr_cpanic("reg: not a Device");
  if (!ISINT(off)) fpr_cpanic("reg: offset not an Int");
  reg_t *r = (reg_t *)fpr_alloc(sizeof(reg_t));
  r->tid = T_REGISTER;
  r->var = width;
  r->addr = ((fpr_dev_t *)dev)->base + (uw)UNTAG(off);
  return (V)r;
}
static V h_reg8(V d, V o) { return mkreg(d, o, 1); }
static V h_reg32(V d, V o) { return mkreg(d, o, 4); }
static V h_read(V rv) {
  if (ISINT(rv) || TID(rv) != T_REGISTER) fpr_cpanic("read: not a Register");
  reg_t *r = (reg_t *)rv;
  return TAG((sw)qos_hal->mmio_read(r->addr, r->var));
}
static V h_write(V rv, V x) {
  if (ISINT(rv) || TID(rv) != T_REGISTER) fpr_cpanic("write: not a Register");
  reg_t *r = (reg_t *)rv;
  uw v;
  if (ISINT(x)) v = (uw)UNTAG(x);
  else if (TID(x) == T_BITS) v = ((bits_t *)x)->val;
  else fpr_cpanic("write: value must be Int or Array Bit");
  qos_hal->mmio_write(r->addr, v, r->var);
  return (V)&fpr_unit;
}
FPR_FN(fpr_g_reg8, h_reg8, 2);
FPR_FN(fpr_g_reg32, h_reg32, 2);
FPR_FN(fpr_g_read, h_read, 1);
FPR_FN(fpr_g_write, h_write, 2);

/* ---- raw pins: not carried by the current QOS HAL table ------------ */
static V h_pin_mode(V pin, V mode) {
  (void)pin;
  (void)mode;
  fpr_cpanic("Pin.mode: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_read(V pin) {
  (void)pin;
  fpr_cpanic("Pin.read: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_write(V pin, V value) {
  (void)pin;
  (void)value;
  fpr_cpanic("Pin.write: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_wire(V source, V destination) {
  (void)source;
  (void)destination;
  fpr_cpanic("Pin.wire: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_feed(V pin, V pattern, V bits) {
  (void)pin;
  (void)pattern;
  (void)bits;
  fpr_cpanic("Pin.feed: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_trace(V value) {
  (void)value;
  fpr_cpanic("Pin trace: capability not granted by this host's HAL table");
  return 0;
}
FPR_FN(fpr_g_Pin_x2emode, h_pin_mode, 2);
FPR_FN(fpr_g_Pin_x2eread, h_pin_read, 1);
FPR_FN(fpr_g_Pin_x2ewrite, h_pin_write, 2);
FPR_FN(fpr_g_Pin_x2ewire, h_pin_wire, 2);
FPR_FN(fpr_g_Pin_x2efeed, h_pin_feed, 3);
FPR_FN(fpr_g_Pin_x2etget, h_pin_trace, 1);
FPR_FN(fpr_g_Pin_x2etlen, h_pin_trace, 1);
FPR_FN(fpr_g_Pin_x2etclear, h_pin_trace, 1);

/* ---- device discovery through the table ----------------------------- */
static fpr_dev_t devcells[8];
static char devnames[8][16];
static int ndevcells;

static V h_device(V nameStr) {
  if (ISINT(nameStr) || TID(nameStr) != T_STR)
    fpr_cpanic("device: name must be a String");
  str_t *s = (str_t *)nameStr;
  for (int i = 0; i < ndevcells; i++) {
    const char *n = devnames[i];
    uw j = 0;
    for (; j < s->len && n[j] && n[j] == (char)s->bytes[j]; j++) {}
    if (j == s->len && n[j] == '\0') return (V)&devcells[i];
  }
  uint64_t base;
  if (qos_hal->dev_lookup((const char *)s->bytes, s->len, &base) &&
      ndevcells < 8 && s->len < 16) {
    fpr_dev_t *d = &devcells[ndevcells];
    d->tid = T_DEVICE;
    d->var = 0;
    d->base = (uw)base;
    for (uw k = 0; k < s->len; k++) devnames[ndevcells][k] = (char)s->bytes[k];
    devnames[ndevcells][s->len] = 0;
    ndevcells++;
    return (V)d;
  }
  fpr_cpanic("device: capability not granted by this host's HAL table");
  return 0;
}
FPR_FN(fpr_g_device, h_device, 1);

/* ---- net: the posix contract, table transport (v6: multi-conn).
 * The FPRISC arg was always there; it is the CONNECTION ID now --
 * netPoll 0 returns the next id with buffered bytes (0 = none), and
 * netRead/netWrite/netClose address that id. */
static V h_netPoll(V d) {
  (void)d;
  return TAG((sw)qos_hal->net_poll());
}
static V h_netRead(V d) {
  char buf[1024];
  int64_t n = qos_hal->net_read(ISINT(d) ? (int64_t)UNTAG(d) : 0, buf, sizeof buf);
  return (V)fpr_mkstr((const uint8_t *)buf, (uw)n);
}
static V h_netWrite(V d, V sv) {
  if (ISINT(sv) || TID(sv) != T_STR) fpr_cpanic("netWrite: not a String");
  str_t *s = (str_t *)sv;
  return TAG((sw)qos_hal->net_write(ISINT(d) ? (int64_t)UNTAG(d) : 0,
                                    (const char *)s->bytes, s->len));
}
static V h_netClose(V d) {
  return TAG((sw)qos_hal->net_close(ISINT(d) ? (int64_t)UNTAG(d) : 0));
}
FPR_FN(fpr_g_netPoll, h_netPoll, 1);
FPR_FN(fpr_g_netRead, h_netRead, 1);
FPR_FN(fpr_g_netWrite, h_netWrite, 2);
FPR_FN(fpr_g_netClose, h_netClose, 1);

/* ---- blk: the disk tier (hal/virt/blk.c's surface, table transport)
 * qosp.disk as 4 KiB pages; every record/log/file notion stays FPRISC
 * policy (mods/qlog.fpr) -- the same module System.qa runs over
 * virtio-blk on native.  entry.c refuses version-mismatched tables,
 * so on a v5 host these entries always exist; blkPages still reports
 * 0 when the host could not open its backing file, the graceful
 * no-disk state system.fpr gates on.  Out-of-range and oversize are
 * panics, byte-identical to virt's driver honesty. */
static V h_blkPages(V d) {
  (void)d;
  if (!qos_hal->blk_pages) return TAG(0); /* pre-v5 table: honest no-disk */
  return TAG((sw)qos_hal->blk_pages());
}
static V h_blkRead(V d, V pv) {
  (void)d;
  if (!ISINT(pv)) fpr_cpanic("blkRead: page must be an Int");
  if (!qos_hal->blk_read)
    fpr_cpanic("blk: capability not granted by this host's HAL table");
  char buf[4096];
  if (qos_hal->blk_read((uint64_t)UNTAG(pv), buf) < 0)
    fpr_cpanic("blk: page out of range");
  return (V)fpr_mkstr((const uint8_t *)buf, 4096);
}
static V h_blkWrite(V d, V pv, V sv) {
  (void)d;
  if (!ISINT(pv)) fpr_cpanic("blkWrite: page must be an Int");
  if (ISINT(sv) || TID(sv) != T_STR) fpr_cpanic("blkWrite: payload must be a String");
  str_t *s = (str_t *)sv;
  if (s->len > 4096) fpr_cpanic("blkWrite: payload exceeds one page");
  if (!qos_hal->blk_write)
    fpr_cpanic("blk: capability not granted by this host's HAL table");
  if (qos_hal->blk_write((uint64_t)UNTAG(pv), (const char *)s->bytes, s->len) < 0)
    fpr_cpanic("blk: page out of range");
  return TAG((sw)s->len);
}
FPR_FN(fpr_g_blkPages, h_blkPages, 1);
FPR_FN(fpr_g_blkRead, h_blkRead, 2);
FPR_FN(fpr_g_blkWrite, h_blkWrite, 3);

/* ---- gfx: the nullable table tier ----------------------------------
 * The renderer (and Mesa's dynamic linking) lives in the HOST image --
 * the one boundary the static philosophy concedes, kept concentrated
 * there; the app stays freestanding.  A host built without GFX=1
 * leaves these entries NULL, and calling one is a missing capability,
 * reported the same honest way stubs.c reports the bus tier. */
static void need_gfx(void) {
  if (!qos_hal->gfx_init)
    fpr_cpanic("gfx: capability not granted by this host (build qosp with GFX=1)");
}
static V h_glInit_ret(void) {
  int w = 0, h = 0;
  if (qos_hal->gfx_dims) qos_hal->gfx_dims(&w, &h);
  V *r = (V *)fpr_alloc(24);
  ((hdr_t *)r)->tid = 4; ((hdr_t *)r)->var = 0;
  r[1] = TAG(w); r[2] = TAG(h);
  return (V)r;
}
static V h_glInit(V wv, V hv) {
  need_gfx();
  if (!ISINT(wv) || !ISINT(hv)) fpr_cpanic("glInit: w h must be Ints");
  qos_hal->gfx_init((int)UNTAG(wv), (int)UNTAG(hv));
  return h_glInit_ret();
}
static V h_glRender(V scene) {
  need_gfx();
  int64_t draws, dynBytes;
  qos_hal->gfx_render((uint64_t)scene, &draws, &dynBytes);
  V *r = (V *)fpr_alloc(24);
  ((hdr_t *)r)->tid = 4; ((hdr_t *)r)->var = 0; /* (draws, dynBytes) */
  r[1] = TAG((sw)draws); r[2] = TAG((sw)dynBytes);
  return (V)r;
}
/* ---- glRenderUi scene ui dist -> (draws, dynBytes): the scene, then the 2D layer */
static V h_glRenderUi(V scene, V ui, V distv) {
  need_gfx();
  if (!qos_hal->gfx_render_ui) fpr_cpanic("gfx: the 2D layer is not granted by this host (a pre-v10 qosp)");
  if (!ISINT(distv)) fpr_cpanic("glRenderUi: dist must be an Int (milli)");
  int64_t draws, dynBytes;
  qos_hal->gfx_render_ui((uint64_t)scene, (uint64_t)ui, (int64_t)UNTAG(distv), &draws, &dynBytes);
  V *r = (V *)fpr_alloc(24);
  ((hdr_t *)r)->tid = 4; ((hdr_t *)r)->var = 0;
  r[1] = TAG((sw)draws); r[2] = TAG((sw)dynBytes);
  return (V)r;
}
static V h_glSavePpm(V pathv) {
  need_gfx();
  if (ISINT(pathv) || TID(pathv) != T_STR) fpr_cpanic("glSavePpm: path must be a String");
  str_t *p = (str_t *)pathv;
  char path[256];
  uw n = p->len < sizeof path - 1 ? p->len : sizeof path - 1;
  for (uw i = 0; i < n; i++) path[i] = (char)p->bytes[i];
  path[n] = 0;
  return TAG(qos_hal->gfx_save_ppm(path));
}
static V h_inputPoll(V u) {
  (void)u;
  /* input is its OWN capability: the portable host grants it via the
   * tty/evdev tier without any GL slot populated.  Checking need_gfx
   * here would refuse a capability the table actually carries. */
  if (!qos_hal->gfx_input_poll)
    fpr_cpanic("input: capability not granted by this host");
  /* uniform shape (Mod.resolve convention): (0, 0, 0) = no event */
  int64_t kind = 0, a = 0, c = 0;
  qos_hal->gfx_input_poll(&kind, &a, &c);
  V *t = (V *)fpr_alloc(32);
  ((hdr_t *)t)->tid = 5; ((hdr_t *)t)->var = 0; /* triple */
  t[1] = TAG((sw)kind); t[2] = TAG((sw)a); t[3] = TAG((sw)c);
  return (V)t;
}
/* ---- snd: sndPlay (wave, f0, f1, ms, vol, delay) -> voice slot -------- */
static V h_sndPlay(V tone) {
  if (!qos_hal->snd_play)
    fpr_cpanic("snd: capability not granted by this host (a pre-v7 qosp)");
  if (ISINT(tone) || TID(tone) != T_TUP6) fpr_cpanic("sndPlay: tone must be (wave, f0, f1, ms, vol, delay)");
  V *f = (V *)((char *)tone + 8);
  int64_t a[6];
  for (int i = 0; i < 6; i++) {
    if (!ISINT(f[i])) fpr_cpanic("sndPlay: tone fields must be Ints");
    a[i] = (int64_t)UNTAG(f[i]);
  }
  return TAG((sw)qos_hal->snd_play(a[0], a[1], a[2], a[3], a[4], a[5]));
}
FPR_FN(fpr_g_sndPlay, h_sndPlay, 1);
/* ---- sndMusic path vol -> 1 playing / 0 off / -1 not found */
static V h_sndMusic(V pathv, V volv) {
  if (!qos_hal->snd_music) fpr_cpanic("snd: music not granted by this host (a pre-v9 qosp)");
  if (ISINT(pathv) || TID(pathv) != T_STR) fpr_cpanic("sndMusic: path must be a String");
  if (!ISINT(volv)) fpr_cpanic("sndMusic: vol must be an Int");
  str_t *p = (str_t *)pathv;
  char path[256];
  uw n = p->len < sizeof path - 1 ? p->len : sizeof path - 1;
  for (uw i = 0; i < n; i++) path[i] = (char)p->bytes[i];
  path[n] = 0;
  return TAG((sw)qos_hal->snd_music(path, (int64_t)UNTAG(volv)));
}
FPR_FN(fpr_g_sndMusic, h_sndMusic, 2);
/* ---- glMesh name text -> triangle count: register a program-carried mesh */
static V h_glMesh(V namev, V textv) {
  need_gfx();
  if (!qos_hal->gfx_mesh_load) fpr_cpanic("gfx: mesh registry not granted by this host (a pre-v8 qosp)");
  if (ISINT(namev) || TID(namev) != T_STR) fpr_cpanic("glMesh: name must be a String");
  if (ISINT(textv) || TID(textv) != T_STR) fpr_cpanic("glMesh: mesh text must be a String");
  str_t *n = (str_t *)namev, *t = (str_t *)textv;
  char name[32];
  uw k = n->len < sizeof name - 1 ? n->len : sizeof name - 1;
  for (uw i = 0; i < k; i++) name[i] = (char)n->bytes[i];
  name[k] = 0;
  return TAG((sw)qos_hal->gfx_mesh_load(name, (const char *)t->bytes, t->len));
}
FPR_FN(fpr_g_glMesh, h_glMesh, 2);
FPR_FN(fpr_g_glInit, h_glInit, 2);
FPR_FN(fpr_g_glRender, h_glRender, 1);
FPR_FN(fpr_g_glRenderUi, h_glRenderUi, 3);
/* ---- timeNow u -> epoch seconds (0 on a host without a clock) */
static V h_timeNow(V u) {
  (void)u;
  if (!qos_hal->clock_now) return TAG(0);
  return TAG((sw)qos_hal->clock_now());
}
FPR_FN(fpr_g_timeNow, h_timeNow, 1);
FPR_FN(fpr_g_glSavePpm, h_glSavePpm, 1);
FPR_FN(fpr_g_inputPoll, h_inputPoll, 1);
