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

/* ---- per-process console capture ------------------------------------
 * Sys.captureConsole pid sends what the actors of a launched process print
 * to a buffer instead of the host console, until Sys.releaseConsole pid;
 * the launcher drains it with Sys.takeConsole pid -- the Editor's Run shows
 * a program's output this way (programs/mods/appjobs.fpr).
 *
 * The buffer keeps the LAST QOS_CAPTURE_KEEP bytes: a program that prints
 * faster than its launcher drains loses its oldest output, and the next
 * take says how much ("[N earlier bytes not kept]"), never silently.  The
 * capture belongs to the actor that asked for it -- only that actor takes
 * or releases it -- and if that actor ends first, its resource list
 * releases the capture (fpr_actor_resource_add): a launcher that is killed
 * cannot leak one.  hal_putc runs on any hart, under the console lock for
 * a print; nothing allocates under g_capture_lock. */
#define QOS_CAPTURE_KEEP (64u * 1024) /* well past the 400 lines the Editor keeps */
#define QOS_CAPTURE_NOTE 64           /* room for the "[N earlier bytes not kept]" line */
typedef struct capture {
  struct capture *next;
  uw pid, owner;  /* the process captured, the actor that captures it */
  uw start, len;  /* the ring: len bytes from start */
  uw lost;        /* bytes overwritten since the last take */
  fpr_resource_t res;
  char ring[QOS_CAPTURE_KEEP];
  char out[QOS_CAPTURE_NOTE + QOS_CAPTURE_KEEP]; /* the owner's take, copied out under the lock */
} capture_t;
static capture_t *g_captures;
static fpr_lock_t g_capture_lock;
extern uw fpr_current_id(void);

static int capture_put(uw pid, char ch) {
  int kept = 0;
  fpr_lock(&g_capture_lock);
  for (capture_t *c = g_captures; c; c = c->next)
    if (c->pid == pid) {
      if (c->len < QOS_CAPTURE_KEEP) {
        c->ring[(c->start + c->len) % QOS_CAPTURE_KEEP] = ch;
        c->len++;
      } else {
        c->ring[c->start] = ch;
        c->start = (c->start + 1) % QOS_CAPTURE_KEEP;
        c->lost++;
      }
      kept = 1;
      break;
    }
  fpr_unlock(&g_capture_lock);
  return kept;
}
static void capture_unlink(capture_t *c) {
  fpr_lock(&g_capture_lock);
  for (capture_t **p = &g_captures; *p; p = &(*p)->next)
    if (*p == c) { *p = c->next; break; }
  fpr_unlock(&g_capture_lock);
}
/* the owner ended without releasing: its resource list calls this */
static void capture_drop(void *arg) {
  capture_unlink((capture_t *)arg);
  buddy_free(arg);
}
static capture_t *capture_owned(uw pid) {
  capture_t *found = 0;
  fpr_lock(&g_capture_lock);
  for (capture_t *c = g_captures; c; c = c->next)
    if (c->pid == pid) { found = c; break; }
  fpr_unlock(&g_capture_lock);
  return found && found->owner == fpr_current_id() ? found : 0;
}

/* ---- the hal_* obligations (actors.c / runtime.c contract) ---------- */
void hal_putc(char c) {
  if (__atomic_load_n(&g_captures, __ATOMIC_ACQUIRE)) {
    uw pid = fpr_current_pid();
    if (pid && capture_put(pid, c)) return;
  }
  qos_hal->putc(c);
}
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
void hal_wfi(void) { qos_hal->hart_wait(fpr_hart()->id); }
/* the CLINT model's mtime (10 MHz ticks, net_raw.c's CLINT_MTIME): the
 * clock the parked sleep (actors.c) and the timer service read */
uint64_t hal_mtime(void) { return qos_hal->mmio_read(0x2000u + 49144u, 8); }
void hal_ipi_send(uw hart) { qos_hal->hart_ring(hart); }
void hal_ipi_clear(uw hart) { qos_hal->hart_clear(hart); }
void hal_timer_park(uw hart) { qos_hal->hart_timer_park(hart); }
void hal_timer_arm(uw hart, uw ticks) { qos_hal->hart_timer_arm(hart, ticks); }

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
static V h_reg8(V d, V o) { fpr_confined_refuse("reg8 (the machine's registers)"); return mkreg(d, o, 1); }
static V h_reg32(V d, V o) { fpr_confined_refuse("reg32 (the machine's registers)"); return mkreg(d, o, 4); }
static V h_read(V rv) {
  fpr_confined_refuse("read (a machine register)");
  if (ISINT(rv) || TID(rv) != T_REGISTER) fpr_cpanic("read: not a Register");
  reg_t *r = (reg_t *)rv;
  return TAG((sw)qos_hal->mmio_read(r->addr, r->var));
}
static V h_write(V rv, V x) {
  fpr_confined_refuse("write (a machine register)");
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
  fpr_confined_refuse("Pin.mode (the pin bus)");
  (void)pin;
  (void)mode;
  fpr_cpanic("Pin.mode: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_read(V pin) {
  fpr_confined_refuse("Pin.read (the pin bus)");
  (void)pin;
  fpr_cpanic("Pin.read: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_write(V pin, V value) {
  fpr_confined_refuse("Pin.write (the pin bus)");
  (void)pin;
  (void)value;
  fpr_cpanic("Pin.write: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_wire(V source, V destination) {
  fpr_confined_refuse("Pin.wire (the pin bus)");
  (void)source;
  (void)destination;
  fpr_cpanic("Pin.wire: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_feed(V pin, V pattern, V bits) {
  fpr_confined_refuse("Pin.feed (the pin bus)");
  (void)pin;
  (void)pattern;
  (void)bits;
  fpr_cpanic("Pin.feed: capability not granted by this host's HAL table");
  return 0;
}
static V h_pin_trace(V value) {
  fpr_confined_refuse("Pin.tget/tlen/tclear (the pin bus)");
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
  fpr_confined_refuse("device (the machine's devices)");
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
  fpr_confined_refuse("netPoll (the network)");
  (void)d;
  return TAG((sw)qos_hal->net_poll());
}
static V h_netRead(V d) {
  fpr_confined_refuse("netRead (the network)");
  char buf[1024];
  int64_t n = qos_hal->net_read(ISINT(d) ? (int64_t)UNTAG(d) : 0, buf, sizeof buf);
  return (V)fpr_mkstr((const uint8_t *)buf, (uw)n);
}
static V h_netWrite(V d, V sv) {
  fpr_confined_refuse("netWrite (the network)");
  if (ISINT(sv) || TID(sv) != T_STR) fpr_cpanic("netWrite: not a String");
  str_t *s = (str_t *)sv;
  return TAG((sw)qos_hal->net_write(ISINT(d) ? (int64_t)UNTAG(d) : 0,
                                    (const char *)s->bytes, s->len));
}
static V h_netClose(V d) {
  fpr_confined_refuse("netClose (the network)");
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
 * no-disk state system.fpr gates on.  A request that cannot complete
 * fail-stops its caller, as on virt (below); argument errors panic. */
/* The deadline: how long a caller waits for its page before the disk counts
 * as stalled, in 10 MHz machine-clock ticks (5 s, as on virt); a test build
 * shortens it.  Past it the caller lets go of its request -- the worker
 * still owns the buffer and frees it when the host call returns -- and
 * fail-stops.  A refused submission (the host refuses while its worker is
 * stalled past the deadline: hal/unix/blk_raw.c), an I/O error and an
 * out-of-range page fail-stop the caller too: its RPC callers hear
 * "dead actor", and the rest of the system runs on. */
#ifndef QOS_BLK_DEADLINE_TICKS
#define QOS_BLK_DEADLINE_TICKS 50000000ULL
#endif
static int64_t disk_wait(uint64_t page, const char *src, uint64_t len, int write, char *dst) {
#ifdef QOS_DISK_TEST_SYNC
  if (write != 2) return write ? qos_hal->blk_write(page, src, len) : qos_hal->blk_read(page, dst);
#endif
  if (!qos_hal->blk_submit || !qos_hal->blk_done || !qos_hal->blk_result || !qos_hal->blk_release)
    fpr_cpanic("blk: asynchronous disk capability not granted");
  void *job = qos_hal->blk_submit(page, src, len, write);
  if (!job) fpr_actor_fail("blk: request refused (the disk worker is stalled past its deadline, or cannot take requests)");
  fpr_actor_cleanup_set(qos_hal->blk_release, job);
  uint64_t start = hal_mtime();
  while (!qos_hal->blk_done(job)) {
    if (hal_mtime() - start >= QOS_BLK_DEADLINE_TICKS) {
      fpr_actor_cleanup_clear(job);
      qos_hal->blk_release(job); /* the worker's reference keeps the buffer */
      fpr_actor_fail("blk: request timed out (the disk worker stalled)");
    }
    fpr_actor_sleep_us(200);
  }
  int64_t result = qos_hal->blk_result(job, dst);
  fpr_actor_cleanup_clear(job);
  qos_hal->blk_release(job);
  return result;
}
static V h_blkPages(V d) {
  fpr_confined_refuse("blkPages (the raw disk)");
  (void)d;
  if (!qos_hal->blk_pages) return TAG(0); /* pre-v5 table: honest no-disk */
  return TAG((sw)qos_hal->blk_pages());
}
static V h_blkRead(V d, V pv) {
  fpr_confined_refuse("blkRead (the raw disk)");
  (void)d;
  if (!ISINT(pv)) fpr_cpanic("blkRead: page must be an Int");
  if (!qos_hal->blk_read)
    fpr_cpanic("blk: capability not granted by this host's HAL table");
  char buf[4096];
  if (disk_wait((uint64_t)UNTAG(pv), 0, 0, 0, buf) < 0)
    fpr_actor_fail("blk: read failed (page out of range, or an I/O error)");
  return (V)fpr_mkstr((const uint8_t *)buf, 4096);
}
static V h_blkWrite(V d, V pv, V sv) {
  fpr_confined_refuse("blkWrite (the raw disk)");
  (void)d;
  if (!ISINT(pv)) fpr_cpanic("blkWrite: page must be an Int");
  if (ISINT(sv) || TID(sv) != T_STR) fpr_cpanic("blkWrite: payload must be a String");
  str_t *s = (str_t *)sv;
  if (s->len > 4096) fpr_cpanic("blkWrite: payload exceeds one page");
  if (!qos_hal->blk_write)
    fpr_cpanic("blk: capability not granted by this host's HAL table");
  if (disk_wait((uint64_t)UNTAG(pv), (const char *)s->bytes, s->len, 1, 0) < 0)
    fpr_actor_fail("blk: write failed (page out of range, or an I/O error)");
  return TAG((sw)s->len);
}
FPR_FN(fpr_g_blkPages, h_blkPages, 1);
FPR_FN(fpr_g_blkRead, h_blkRead, 2);
FPR_FN(fpr_g_blkWrite, h_blkWrite, 3);
/* ABI v19 gives operation 2 its barrier meaning. The worker serializes it
 * after preceding writes; a timeout abandons only the caller reference. */
static V h_blkFlush(V d) {
  fpr_confined_refuse("blkFlush (the raw disk)");
  (void)d;
  return TAG((sw)disk_wait(0, 0, 0, 2, 0));
}
FPR_FN(fpr_g_blkFlush, h_blkFlush, 1);

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
/* glHas 0 -> Int: 1 when this host grants the gfx tier, 0 when not -- so a
 * system service can decline to claim /services/graphics instead of
 * panicking on its first frame */
static V h_glHas(V d) { (void)d; return TAG(qos_hal->gfx_init ? 1 : 0); }
FPR_FN(fpr_g_glHas, h_glHas, 1);
static V h_glInit_ret(void) {
  int w = 0, h = 0;
  if (qos_hal->gfx_dims) qos_hal->gfx_dims(&w, &h);
  V *r = (V *)fpr_alloc(24);
  ((hdr_t *)r)->tid = 4; ((hdr_t *)r)->var = 0;
  r[1] = TAG(w); r[2] = TAG(h);
  return (V)r;
}
static V h_glInit(V wv, V hv) {
  fpr_confined_refuse("glInit (the display)");
  need_gfx();
  if (!ISINT(wv) || !ISINT(hv)) fpr_cpanic("glInit: w h must be Ints");
  qos_hal->gfx_init((int)UNTAG(wv), (int)UNTAG(hv));
  return h_glInit_ret();
}
static V h_glRender(V scene) {
  fpr_confined_refuse("glRender (the display)");
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
  fpr_confined_refuse("glRenderUi (the display)");
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
  fpr_confined_refuse("glSavePpm (the display)");
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
  fpr_confined_refuse("inputPoll (the keyboard and pointer)");
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
  fpr_confined_refuse("sndPlay (the sound device)");
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
  fpr_confined_refuse("sndMusic (the sound device)");
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
  fpr_confined_refuse("glMesh (the display)");
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

/* Shared actor binding; Portable uses its socket transport inside the actor. */
#include "../../hal/net_actor_bridge.c"

/* ---- Sys.captureConsole / takeConsole / releaseConsole -------------------
 * (the capture above; declared in core/foreign.fpr) */
static V h_capture_console(V pidv) {
  fpr_confined_refuse("Sys.captureConsole (another program's console)");
  if (!ISINT(pidv)) fpr_cpanic("Sys.captureConsole: pid must be an Int");
  if (UNTAG(pidv) <= 0) return fpr_mkresult(1, "pid 0 is the system's own console");
  uw pid = (uw)UNTAG(pidv);
  capture_t *c = (capture_t *)buddy_alloc(sizeof(capture_t));
  if (!c) return fpr_mkresult(1, "no memory for a console capture");
  c->pid = pid;
  c->owner = fpr_current_id();
  c->start = c->len = c->lost = 0;
  fpr_lock(&g_capture_lock);
  for (capture_t *e = g_captures; e; e = e->next)
    if (e->pid == pid) {
      fpr_unlock(&g_capture_lock);
      buddy_free(c);
      return fpr_mkresult(1, "that process's console is already captured");
    }
  c->next = g_captures;
  __atomic_store_n(&g_captures, c, __ATOMIC_RELEASE);
  fpr_unlock(&g_capture_lock);
  if (!fpr_actor_resource_add(&c->res, capture_drop, c)) {
    capture_unlink(c);
    buddy_free(c);
    return fpr_mkresult(1, "this actor cannot own a console capture");
  }
  return fpr_mkresult(0, "");
}
FPR_FN(fpr_g_Sys_x2ecaptureConsole, h_capture_console, 1);

static uw put_dec(char *d, uw v) {
  char t[24];
  uw n = 0, k = 0;
  do { t[n++] = (char)('0' + v % 10); v /= 10; } while (v);
  while (n) d[k++] = t[--n];
  return k;
}
static V h_take_console(V pidv) {
  fpr_confined_refuse("Sys.takeConsole (another program's console)");
  if (!ISINT(pidv)) fpr_cpanic("Sys.takeConsole: pid must be an Int");
  capture_t *c = capture_owned((uw)UNTAG(pidv));
  if (!c) return fpr_mkresult(1, "no console capture of that process by this actor");
  uw n = 0;
  fpr_lock(&g_capture_lock);
  if (c->lost) {
    const char *a = "[", *b = " earlier bytes not kept]\n";
    while (*a) c->out[n++] = *a++;
    n += put_dec(c->out + n, c->lost);
    while (*b) c->out[n++] = *b++;
  }
  for (uw i = 0; i < c->len; i++) c->out[n++] = c->ring[(c->start + i) % QOS_CAPTURE_KEEP];
  c->start = c->len = c->lost = 0;
  fpr_unlock(&g_capture_lock);
  return fpr_mkresultn(0, c->out, n);
}
FPR_FN(fpr_g_Sys_x2etakeConsole, h_take_console, 1);

static V h_release_console(V pidv) {
  fpr_confined_refuse("Sys.releaseConsole (another program's console)");
  if (!ISINT(pidv)) fpr_cpanic("Sys.releaseConsole: pid must be an Int");
  capture_t *c = capture_owned((uw)UNTAG(pidv));
  if (!c) return fpr_mkresult(1, "no console capture of that process by this actor");
  capture_unlink(c);
  fpr_actor_resource_remove(&c->res);
  buddy_free(c);
  return fpr_mkresult(0, "");
}
FPR_FN(fpr_g_Sys_x2ereleaseConsole, h_release_console, 1);

/* Sys.memTotal () -> Int: the host's physical memory in bytes, 0 when it
 * cannot say (ABI v22) -- what a launcher sizes a confined program's budget
 * by, since the arena is address space, not memory */
static V h_mem_total(V u) {
  (void)u;
  return TAG((sw)(qos_hal->mem_total ? qos_hal->mem_total() : 0));
}
FPR_FN(fpr_g_Sys_x2ememTotal, h_mem_total, 1);
