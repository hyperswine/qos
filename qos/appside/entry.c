/* entry.c (qosapp) -- qos_app_entry: proc_entry.c's hosted sibling.
 *
 * Same job as fpr_process_entry on virt (docs/PROCESS-LOADING.md):
 * turn a granted arena into a running single-hart FPRISC world and
 * hand back the main actor's result.  The differences are exactly the
 * platform's:
 *
 *   - the hart cell is a PLAIN GLOBAL (fpr_posix_hart, FPR_QOSAPP in
 *     fpr.h), not the tp register -- so there is no save/restore dance
 *     with the caller: the host's own hart state lives in the HOST
 *     image's TLS, a different symbol in a different image.  The
 *     whole tp essay in proc_entry.c dissolves.
 *   - the HAL arrives as a table pointer in the boot record instead of
 *     resolving at link time; qosapp/hal.c holds the dispatching
 *     implementations of the hal_* obligations and the fpr_g_ shims.
 *   - the result leaves as a rendered string, not a V (the host has no
 *     runtime to read a V with).
 */
#include "fpr.h"
#include "qos_abi.h"

/* the TLS BORROW (ABI v2, qos_abi.h): the one plain global the
 * deTlsQosApp* passes and fpr.h's FPR_QOSAPP accessors index the
 * host's per-hart-thread borrow block through.  Written once below,
 * before any generated code or hart loop runs. */
#if defined(FPR_QOSAPP_SINGLE)
fpr_hart_t *fpr_posix_hart;
#elif !defined(__aarch64__)
uw fpr_g_tlsoff; /* x64 only: the %fs borrow displacement (fpr.h) */
#endif /* aarch64 v3: the hart rides x28, no cell to declare (fpr.h) */

const qos_hal_t *qos_hal; /* installed before anything can call out */

static const unsigned char *g_caps_bytes;
static uw g_caps_len;
static V h_sys_caps(V d) {
  (void)d;
  return (V)fpr_mkstr(g_caps_bytes ? g_caps_bytes : (const unsigned char *)"",
                      g_caps_len);
}
FPR_FN(fpr_g_Sys_x2ecaps, h_sys_caps, 1);

/* the storage syscall (the host's System.qa-analogue): tag 2 = kv
 * append, tag 3 = kv replay -- the FPRISC surface is Sys.storeReq,
 * byte-compatible with the virt process model's channel */
static int64_t (*g_syscall)(uint64_t, const char *, uint64_t, char *, uint64_t);

/* the strong Sys.sleepUs backend for qosp apps: weak/strong linking
 * cannot cross the image boundary (runtime.c's weak default is what
 * the app links), so the sleep rides the syscall channel like every
 * other host service.  Standalone runs (no channel) keep the spin. */
int fpr_hal_sleep_us(uintptr_t us) {
  if (!g_syscall) return 0;
  char buf[24];
  int n = 0;
  if (us == 0) return 1;
  { /* minimal utoa: freestanding, no snprintf here */
    char tmp[24];
    int i = 0;
    uintptr_t v = us;
    while (v) { tmp[i++] = (char)('0' + (v % 10)); v /= 10; }
    while (i) buf[n++] = tmp[--i];
  }
  g_syscall(6, buf, (uint64_t)n, 0, 0);
  return 1;
}
static char g_sysout[256 * 1024];

/* ---- plugins: relocatable images completed by name ---------------------
 * (docs/2026-10-01-IMPORT-TABLE.md)  A plugin is linked at 0.  The app
 * places it in a block of its OWN heap, like any other memory, moves its
 * address words by where the block is (RELOC), and completes its imports
 * of the runtime BY NAME from this image's export table (IMPORT,
 * qos_exports: tools/mkimports.py and tools/mkexports.py).  Then it asks
 * the host to make the code executable (tag 4), registers the block as an
 * image (its cells are statics: fpr_in_heap) and its module table (mod.c).
 * No slot, no address chosen at build time, no tie to one shell build: a
 * plugin loads into any app that exports what it needs, and says what is
 * missing when one does not. */
int fpr_mod_attach(const uw *tab);
/* defined by tools/mkexports.py's table, absent in the FIRST link (which
 * ignores unresolved symbols: qos-app.mk).  Not weak: a weak extern is
 * reached through the GOT, whose slot the image's relocation list cannot
 * move (mkqa refuses R_AARCH64_*_GOT_* by name), and a relocatable image
 * (2026-10-02) reaches every symbol by address. */
extern const uw qos_exports[];

static qos_span_t span_of(V v, const char *who) {
  if (ISINT(v) || ((hdr_t *)v)->tid != T_STR) fpr_cpanic(who);
  str_t *s = (str_t *)v;
  return (qos_span_t){s->bytes, s->len};
}
/* the export row named n[0..len), or 0 (rows sorted by name, bytewise) */
static const qos_export_t *export_find(const unsigned char *n, uw len) {
  const qos_export_t *t = (const qos_export_t *)(qos_exports + 1);
  uw lo = 0, hi = qos_exports[0];
  while (lo < hi) {
    uw mid = lo + (hi - lo) / 2;
    const unsigned char *m = (const unsigned char *)t[mid].name;
    uw i = 0;
    while (i < len && m[i] && m[i] == n[i]) i++;
    int c = i == len ? (m[i] ? -1 : 0) : (!m[i] ? 1 : (n[i] < m[i] ? -1 : 1));
    if (c == 0) return &t[mid];
    if (c < 0) hi = mid; else lo = mid + 1;
  }
  return 0;
}
static uw dec(const unsigned char **p, const unsigned char *e) {
  uw v = 0;
  while (*p < e && **p >= '0' && **p <= '9') v = v * 10 + (uw)(*(*p)++ - '0');
  return v;
}
/* the n-th element of a List String, as a span */
static qos_span_t list_str(V l, uw n, const char *who) {
  for (;;) {
    if (ISINT(l) || TID(l) != T_LIST || ((hdr_t *)l)->var != 1) fpr_cpanic(who);
    if (n == 0) return span_of(*(V *)((char *)l + 8), who);
    l = *(V *)((char *)l + 8 + sizeof(uw));
    n--;
  }
}
/* fill each import: a slot gets the exporter's address, a placeholder a
 * copy of its object.  Returns 0, or the refusal (written into err). */
static const char *complete_imports(unsigned char *base, uw memsz, qos_span_t imp,
                                    char *err, uw errcap) {
  const unsigned char *p = imp.p, *e = imp.p + imp.n;
  uw nerr = 0, missing = 0;
  const char *why = 0;
  while (p < e) {
    unsigned char kind = *p++;
    if (p < e && *p == ' ') p++;
    uw off = dec(&p, e);
    if (p < e && *p == ' ') p++;
    uw size = dec(&p, e);
    if (p < e && *p == ' ') p++;
    const unsigned char *nm = p;
    while (p < e && *p != '\n') p++;
    uw nlen = (uw)(p - nm);
    if (p < e) p++;
    if ((kind != 'c' && kind != 'd') || !nlen || off + size > memsz || off + size < off)
      return "the IMPORT section is malformed";
    const qos_export_t *x = export_find(nm, nlen);
    if (!x) { /* collect every missing name, then refuse once */
      const char *pre = missing ? ", " : "the plugin needs ";
      for (const char *c = pre; *c && nerr + 1 < errcap; c++) err[nerr++] = *c;
      for (uw i = 0; i < nlen && nerr + 1 < errcap; i++) err[nerr++] = (char)nm[i];
      missing++;
      continue;
    }
    if (kind == 'c') {
      *(uw *)(void *)(base + off) = (uw)x->addr;
    } else {
      if (x->size != size) { why = "a data import's size differs from the app's (rebuild the plugin)"; continue; }
      __builtin_memcpy(base + off, (const void *)(uintptr_t)x->addr, size);
    }
  }
  if (missing) {
    const char *post = ", which this app does not export";
    for (const char *c = post; *c && nerr + 1 < errcap; c++) err[nerr++] = *c;
    err[nerr] = 0;
    return err;
  }
  return why;
}

/* An attached image's record sits at the head of its buddy block, before
 * the 64 KiB-aligned image.  Its pid is 0 until Sys.spawnApp adopts the
 * image its root function lives in (runtime.c fpr_image_adopt); from then
 * on it ends with that process: the reap hook below frees the block once no
 * actor of the pid is left, the native loader's rule (loader/process.c
 * image_quiet).  An image that is only ever used as a module, never
 * launched, stays pid 0 and immortal. */
typedef struct {
  fpr_image_t im;
  uint64_t base, execsz; /* the pages the host made r-x: made r-w again before reuse */
  int ending;
} plug_image_t;
static fpr_lock_t g_plug_lock; /* serializes teardown against reaps on other harts */
static void plug_image_quiet(uw pid) {
  fpr_lock(&g_plug_lock);
  plug_image_t *pi = (plug_image_t *)fpr_image_of_pid(pid);
  if (!pi || pi->ending || fpr_pid_live(pid)) { fpr_unlock(&g_plug_lock); return; }
  pi->ending = 1;
  fpr_image_remove(&pi->im);
  fpr_unlock(&g_plug_lock);
  if (g_syscall) {
    char err[128];
    qos_unload_t u = {pi->base, pi->execsz};
    err[0] = 0;
    if (g_syscall(QOS_SYS_UNLOADQA, (const char *)&u, sizeof u, err, sizeof err) < 0)
      fpr_cpanic(err[0] ? err : "plugin unload refused by the host");
  }
  buddy_free(pi);
}

/* Sys.images : Int -> Int -- attached images now (a launched one goes when
 * its process has ended; the native loader's Sys.images is the same count) */
static V h_sys_images(V d) { (void)d; return TAG((sw)fpr_image_count()); }
FPR_FN(fpr_g_Sys_x2eimages, h_sys_images, 1);

/* LOAD's claims, checked BEFORE anything is placed: `sha` over IMAGE and
 * `relsha` over RELOC || IMPORT (qos/portable/sha256.c, linked into apps).  A
 * tampered relocation list must not move a single word, so the host's own
 * check after placement is too late to be the first one
 * (docs/2026-10-03-PREEXISTING-FAILURES.md). */
void qosp_sha256(const unsigned char *msg, uint64_t n, unsigned char out[32]);
static int digest_is(qos_span_t want, const unsigned char *a, uw an, const unsigned char *b, uw bn) {
  if (!want.n) return 1; /* nothing claimed, nothing to refuse */
  unsigned char d[32];
  if (bn) {
    unsigned char *both = (unsigned char *)buddy_alloc(an + bn);
    if (!both) return 0;
    __builtin_memcpy(both, a, an);
    __builtin_memcpy(both + an, b, bn);
    qosp_sha256(both, an + bn, d);
    buddy_free(both);
  } else {
    qosp_sha256(a, an, d);
  }
  if (want.n != 64) return 0;
  static const char hx[] = "0123456789abcdef";
  for (int i = 0; i < 32; i++)
    if (want.p[2 * i] != hx[d[i] >> 4] || want.p[2 * i + 1] != hx[d[i] & 15]) return 0;
  return 1;
}

/* Sys.attachImage <id> <abi> <sha> <relsha> <nums> [IMAGE, RELOC, IMPORT] -> Ok "" | Err
 * reason: nums is mods/qaimg.fpr's [base, entry, execsz, rwoff, memsz] (base
 * 0: relocatable); programs call Plug.attach with the .qa bytes. */
static V h_sys_attach_image(V idv, V abiv, V shav, V relshav, V numsv, V secsv) {
  if (!g_syscall) return fpr_mkresult(1, "no syscall channel (standalone run)");
  uw n[5];
  if (!fpr_list_ints(numsv, n, 5)) fpr_cpanic("Sys.attachImage: nums must be [base, entry, execsz, rwoff, memsz]");
  qos_span_t img = list_str(secsv, 0, "Sys.attachImage: sections must be [IMAGE, RELOC, IMPORT]");
  qos_span_t rel = list_str(secsv, 1, "Sys.attachImage: sections must be [IMAGE, RELOC, IMPORT]");
  qos_span_t imp = list_str(secsv, 2, "Sys.attachImage: sections must be [IMAGE, RELOC, IMPORT]");
  if (n[0] != 0)
    return fpr_mkresult(1, "not a relocatable plugin (linked for a fixed slot): rebuild it");
  if (!digest_is(span_of(shav, "Sys.attachImage: sha must be a String"), img.p, img.n, 0, 0))
    return fpr_mkresult(1, "IMAGE sha256 mismatch (corrupt archive)");
  if (!digest_is(span_of(relshav, "Sys.attachImage: relsha must be a String"), rel.p, rel.n, imp.p, imp.n))
    return fpr_mkresult(1, "RELOC sha256 mismatch (corrupt archive)");
  uw memsz = n[4];
  const uw align = 64u * 1024; /* the link script's W^X page: 4 K and 16 K hosts alike */
  void *blk = buddy_alloc(sizeof(plug_image_t) + align + memsz);
  if (!blk) return fpr_mkresult(1, "no memory for the plugin");
  unsigned char *base = (unsigned char *)(((uw)blk + sizeof(plug_image_t) + align - 1) & ~(align - 1));
  fpr_qaimg_t q = {(uw)base, n[1], n[2], n[3], memsz};
  fpr_elf_load_t ld = fpr_qaimg_place(&q, img.p, img.n, base, memsz);
  const char *bad = ld.ok ? fpr_qaimg_relocate(base, img.n, rel.p, rel.n) : ld.err;
  if (!bad) bad = complete_imports(base, memsz, imp, g_sysout, sizeof g_sysout);
  if (bad) {
    buddy_free(blk);
    return fpr_mkresult(1, bad);
  }
  qos_plugin_t pl = {
      span_of(idv, "Sys.attachImage: id must be a String"),
      span_of(abiv, "Sys.attachImage: abi must be a String"),
      span_of(shav, "Sys.attachImage: sha must be a String"),
      img, (uint64_t)(uintptr_t)base, n[1], n[2], n[3], memsz,
      span_of(relshav, "Sys.attachImage: relsha must be a String"), rel, imp,
  };
  g_sysout[0] = 0;
  int64_t r = g_syscall(QOS_SYS_LOADQA, (const char *)&pl, sizeof pl, g_sysout, sizeof g_sysout);
  if (r <= 0) {
    buddy_free(blk); /* refused before any page changed protection */
    return fpr_mkresult(1, g_sysout[0] ? g_sysout : "plugin load failed");
  }
  /* the block's cells are statics now, owned by no process until a launch
   * adopts the image (pid 0) */
  plug_image_t *pi = (plug_image_t *)blk;
  pi->im.lo = (char *)blk - sizeof(uw);
  pi->im.hi = (char *)blk + buddy_block_usable_size(blk);
  pi->im.pid = 0;
  pi->im.owner = pi;
  pi->base = (uint64_t)(uintptr_t)base;
  pi->execsz = n[2];
  pi->ending = 0;
  if (!fpr_pid_quiet) fpr_pid_quiet = plug_image_quiet;
  fpr_image_add(&pi->im);
  if (fpr_mod_attach((const uw *)(uintptr_t)r))
    return fpr_mkresult(1, "module registry full");
  return fpr_mkresult(0, "");
}
FPR_FN(fpr_g_Sys_x2eattachImage, h_sys_attach_image, 6);

/* Sys.compile <profile> <source> -> Ok asm | Err reason: the host-
 * side fpr compiler server, reached over the syscall channel (tag 7,
 * qos_abi.h) -- qosp bridges to the daemon's unix socket, and the
 * "ok\n"/"err\n" status line framed into the reply is parsed HERE so
 * callers get one Result.  The profile is a token the daemon
 * whitelists (qos-portable | bare-metal), never argv passthrough. */
static V h_sys_compile(V profv, V srcv) {
  if (ISINT(profv) || ((hdr_t *)profv)->tid != T_STR)
    fpr_cpanic("Sys.compile: profile must be a String");
  if (ISINT(srcv) || ((hdr_t *)srcv)->tid != T_STR)
    fpr_cpanic("Sys.compile: source must be a String");
  if (!g_syscall) return fpr_mkresult(1, "no syscall channel (standalone run)");
  str_t *prof = (str_t *)profv;
  str_t *src = (str_t *)srcv;
  uint64_t plen = prof->len + 1 + src->len;
  char *req = (char *)fpr_alloc(plen);
  for (uw i = 0; i < prof->len; i++) req[i] = (char)prof->bytes[i];
  req[prof->len] = '\n';
  for (uw i = 0; i < src->len; i++) req[prof->len + 1 + i] = (char)src->bytes[i];
  int64_t r = g_syscall(7, req, plen, g_sysout, sizeof g_sysout);
  if (r == -2) return fpr_mkresult(1, "no compiler server (start tools/fprd.py)");
  if (r == -4) return fpr_mkresult(1, "compiled asm larger than the channel buffer");
  if (r < 3) return fpr_mkresult(1, "compiler channel error");
  if (g_sysout[0] == 'o' && g_sysout[1] == 'k' && g_sysout[2] == '\n')
    return fpr_mkresultn(0, g_sysout + 3, (uw)r - 3);
  if (r >= 4 && g_sysout[0] == 'e' && g_sysout[1] == 'r' && g_sysout[2] == 'r' &&
      g_sysout[3] == '\n')
    return fpr_mkresultn(1, g_sysout + 4, (uw)r - 4);
  return fpr_mkresult(1, "malformed compiler reply");
}
FPR_FN(fpr_g_Sys_x2ecompile, h_sys_compile, 2);

static V h_sys_store_req(V tagv, V payv) {
  if (!ISINT(tagv)) fpr_cpanic("Sys.storeReq: tag must be an Int");
  if (ISINT(payv) || ((hdr_t *)payv)->tid != T_STR)
    fpr_cpanic("Sys.storeReq: payload must be a String");
  if (!g_syscall) return fpr_mkresult(1, "no syscall channel (standalone run)");
  str_t *s = (str_t *)payv;
  int64_t r = g_syscall((uw)UNTAG(tagv), (const char *)s->bytes, s->len,
                        g_sysout, sizeof g_sysout);
  if (r == -2) return fpr_mkresult(1, "no disk");
  if (r < 0) return fpr_mkresult(1, "storage error");
  return fpr_mkresultn(0, g_sysout, (uw)r);
}
FPR_FN(fpr_g_Sys_x2estoreReq, h_sys_store_req, 2);

/* the function start_hart runs on each new host thread: join the
 * scheduler as hart i.  fpr_hart_secondary sets tp (through the
 * borrow) and enters the hart loop; the loop returns when
 * fpr_process_done ends the world, and the host joins the thread. */
static void qos_hart_thread(uint64_t i) { fpr_hart_secondary((int)i); }

/* #23: the app end of the unified log plane -- host lines land in the
 * sev-3 ring (LOG_SEVS' fourth axis), same substrate as log/logWarn/
 * logErr, so /logs/host is just one more path over Sys.logSnap 3. */
static void qos_host_ring_sink(const char *line, uint64_t n) {
  fpr_logput(3, line, (uw)n);
}

/* #24: last words to disk.  Runs inside fpr_cpanic's re-entrancy
 * guard; the syscall channel is the host's own code on this thread
 * (fopen/fwrite), no actor machinery involved, so it is one of the
 * few things a dying world can still safely do. */
static void qos_panic_persist(const char *msg, uw n) {
  if (!g_syscall) return;
  static char rec[192];
  const char *pre = "sys/panic\n";
  uw p = 0;
  while (pre[p]) { rec[p] = pre[p]; p++; }
  if (n > sizeof rec - p) n = sizeof rec - p;
  for (uw i = 0; i < n; i++) rec[p + i] = msg[i];
  char out[8];
  g_syscall(2, rec, p + n, out, sizeof out);
}

int64_t qos_app_entry(const qos_boot_t *boot, char *result_out,
                      uw result_cap) {
  extern char _bss_start[], _bss_end[];
  /* elfload.c zeroes memsz-filesz tails, which covers .bss when the
   * linker merges it into the loaded PT_LOAD; clearing again here is
   * cheap and makes this function correct on its own (same reasoning
   * as proc_entry.c).  NOTE this runs before any global above is
   * trusted -- it also zeroes them, which is their initial state. */
  for (char *p = _bss_start; p < _bss_end; p++) *p = 0;

  if (!boot || boot->abi_version != QOS_ABI_VERSION) return -1;
  qos_hal = boot->hal; /* first: panics from here on can reach putc */
  /* the host's fault handler asks this which actor ran off its stack */
  qos_hal->set_stack_query((void *(*)(uint64_t *, uint64_t *))fpr_current_stack);
  if (!qos_hal || qos_hal->version != QOS_ABI_VERSION) return -1;
#if !defined(FPR_QOSAPP_SINGLE) && !defined(__aarch64__)
  fpr_g_tlsoff = boot->tls_off; /* before ANY tp read: fpr_set_tp below
                                 * already goes through the borrow.
                                 * (aarch64 v3 needs nothing here: the
                                 * hart rides x28 */
#endif

  fpr_hart_t *h = &fpr_harts[0];
  h->id = 0;
  /* ---- the arena is OURS (ABI v12) ---------------------------------
   * The host mapped it and loaded us at its start; everything past the
   * image is handed over raw, and this image's buddy runs over it --
   * the same lower allocator a machine boot has, behind the same
   * memory actor (docs/MEMORY.md); plugins are placed in its blocks
   * too.  Hart 0's first slab is an ordinary block, taken directly (no
   * actor exists yet). */
  {
    uw minb = 64u * 1024; /* buddy's BUDDY_MIN_BLOCK: the seed alignment */
    uw lo = ((uw)boot->arena_base + (minb - 1)) & ~(minb - 1);
    uw hi = (uw)boot->arena_base + boot->arena_size;
    if (!boot->arena_size || hi <= lo + 4 * minb) return -1;
    buddy_init((void *)lo, hi - lo);
    fpr_heap_lo = (char *)boot->arena_base; /* fpr_in_heap's span: run-time, from the */
    fpr_heap_hi = (char *)hi;               /* boot record -- never linked in (v14) */
    fpr_mem_own = 1;
  }
  {
    static void *boot_bkts[FPR_NBUCKETS]; /* hart 0 lives forever */
    fpr_pool_init(&h->pool, boot_bkts);
  }
  {
    fpr_slab_t *sl = (fpr_slab_t *)fpr_mem_take_direct(256u * 1024);
    if (!sl) return -1;
    sl->next = 0;
    sl->owner = &h->pool;
    sl->escaped = 0;
    sl->holds = 0;
    sl->hp = (char *)(sl + 1);
    sl->end = (char *)sl + buddy_block_usable_size(sl);
    h->pool.cur = sl;
  }
  h->current = 0;
  h->rq_head = h->rq_tail = 0;
  h->idle = 0;
  h->fuel_preempts = 0;
  h->rpos = 0;
  fpr_set_tp(h); /* FPR_POSIX form: assigns the plain global */

  /* ---- the unified log plane (ABI v4) --------------------
   * Hand the host our ring writer: every qos_hostlog line from here
   * on -- and every pending boot line, replayed in order -- lands in
   * the sev-3 (host) ring as well as stderr, so /logs/host shows the
   * host's story from inside the app.  After fpr_set_tp: the echo
   * path takes locks and putc, both live by now, and needs no pool. */
  if (qos_hal->set_log_sink) qos_hal->set_log_sink(qos_host_ring_sink);

  g_caps_bytes = boot->caps;
  g_caps_len = boot->caps_len;
  g_syscall = boot->syscall_fn;
  /* #24: persist a panic's last words through the storage syscall as a
   * "sys/panic\n<msg>" record -- the restart loop stops eating its own
   * evidence (Disk.qa shows the record on the next boot). */
  fpr_panic_persist = qos_panic_persist;
  fpr_grow_memory = 0; /* v12: no host grants -- the arena is ours */
  fpr_is_process = 1;  /* still a hosted process: the exit returns to the host */
  fpr_process_done = 0;

  /* ---- multi-hart (ABI v2): resolve, init, start ------------------
   * The host resolved a desired count (hal->nharts); clamp to this
   * image's compile-time cap.  Hart blocks 1..live-1 need only their
   * id -- .bss zero is a correct empty pool/backlog, and each hart's
   * first allocation pulls a grant exactly like hart 0's overflow
   * path.  Threads come from the host (start_hart): the app is
   * freestanding and cannot make them itself; each thread's borrow
   * block already exists (host __thread), so fpr_hart_secondary's
   * fpr_set_tp lands in the right slot from the first instruction. */
  uw live = qos_hal->nharts ? qos_hal->nharts : 1;
  if (live > FPR_NHARTS) live = FPR_NHARTS;
  if (!qos_hal->start_hart) live = 1; /* v1-shaped host: honest fallback */
  fpr_live_harts = live;
  for (uw i = 1; i < live; i++) {
    fpr_hart_t *hi = &fpr_harts[i];
    hi->id = i;
    hi->fuel = 0;
  }

  fpr_actors_init(); /* actor 0 (main) onto hart 0 */
  for (uw i = 1; i < live; i++)
    if (qos_hal->start_hart(i, qos_hart_thread))
      fpr_cpanic("boot: start_hart failed");
  fpr_hart_main(0);  /* returns when actor 0 finishes (fpr_is_process
                      * routes the exit through fpr_process_done --
                      * which also ends every secondary hart loop, so
                      * the host's joins are prompt) */

  V result = fpr_process_result_get();
  /* render into the host's buffer: fpr_prim_fn_str allocates the
   * string in OUR arena, which stays mapped until the host tears the
   * arena down -- but copying out means the host never has to care */
  V s = fpr_prim_fn_str(result);
  str_t *st = (str_t *)s;
  uw n = st->len < result_cap - 1 ? st->len : result_cap - 1;
  for (uw i = 0; i < n; i++) result_out[i] = (char)st->bytes[i];
  result_out[n] = 0;
  return 0;
}
