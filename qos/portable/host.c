/* main.c (portable) -- qosp: the QOS Portable host for linux-x86-64.
 *
 *     qosp [--yes] [--trace] <app.qa>
 *
 * QOS Portable is NOT an OS: it is a hosting runtime that runs ONE
 * FP-RISC program, built for QOS-x86_64 (fprc --target=qx64) and
 * packaged as a .qa, by satisfying the program's std assumptions
 * through a HAL table -- the same relationship the JVM has to a .jar,
 * or System.qa has to a loaded process on virt.  The staging below
 * deliberately mirrors the QOS Native bootstrap's three stages, scaled
 * to what a host OS makes trivial:
 *
 *   Stage 1, Initializer -- test the "hardware" (can the fixed arena
 *     actually be mapped where the app was linked?), build the HAL
 *     table as in-memory C ABI functions (haltab.c).  TRACE output
 *     when asked, off by default, exactly the design's TRACE=TRUE.
 *   Stage 2, Loader -- read the .qa (the app owns the arena past its
 *     image, abi v12: no host allocator over it),
 *     parse the manifest, run the permission gate (required perms are
 *     compulsory: any denial refuses the launch, docs/QA-FORMAT.md);
 *     reserve the image slot; elfload the QOS-x86_64 ELF into it;
 *     assemble the boot record (HAL table, heap grant, growth
 *     callback, serialized caps, storage syscall).
 *   Stage 3 -- hand control to the app's own entry: from here the
 *     app's OWN scheduler (its linked copy of actors.c) runs its
 *     actors on this thread; the host is dormant until the result
 *     comes back.  There is no Memory.qa/System.qa process tier here
 *     because there is only one program -- the growth callback IS the
 *     Memory.qa analogue, the syscall trampoline the System.qa one.
 */
#include "qos_abi.h"
#include "snd_raw.h"

/* ---- the ABI stamp (kills the apps-qa desync class) -----------------
 * fprc stamps `abi = "<QOS_ABI_VERSION>.<codegenRev>"` into every
 * manifest at pack time; a mismatch used to be an undiagnosable crash
 * mid-run.  One honest line instead.  The rev here must track
 * Codegen.hs codegenRev (or be passed as -DQOSP_CODEGEN_REV). */
#ifndef QOSP_CODEGEN_REV
#define QOSP_CODEGEN_REV 7
#endif
#include "hostlog.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/mman.h>
#include <unistd.h>
#include <signal.h>
#include <sys/ucontext.h>
#include <pthread.h>

/* runtime/core, compiled hosted into qosp (qaimg.c only: the host
 * keeps no allocator over the arena since abi v12) */
#include "fpr.h"

const qos_hal_t *qosp_hal_table(void);
void qosp_hal_set_smp(uint64_t nharts, int (*sh)(uint64_t, void (*)(uint64_t)));
void qosp_store_bind(const char *app_id);
int64_t qosp_store_call(uint64_t, const char *, uint64_t, char *, uint64_t);

static int g_trace;

#define TRACE(...) \
  do { if (g_trace) qos_hostlog("qosp: " __VA_ARGS__); } while (0)

/* ---- runtime plugin loader (syscall tag 4, qos_abi.h) ---------------
 * Load a plugin .qa into the reserved plugin window from the BYTES the
 * app hands over -- the app read them off qosp.disk (mods/qlog over
 * the blk tier), so name->bytes resolution is FPRISC's job and the
 * host filesystem is out of the loop entirely.  Parse the QAR2
 * container, place its segments (they must all lie inside the window
 * -- the image was linked for its QOS_PLUG_BASE sub-slot), enforce the
 * identical W^X discipline as the shell image, and hand back the
 * module-table address (the plugin's e_entry -- ENTRY(fpr_modtab) in
 * link-qosplug.ld).  Up to PLUG_MAX images at distinct sub-slots;
 * re-load / overlap refused (v1: no unload). */
#define PLUG_MAX 8
static struct { uintptr_t lo, hi; } plug_ranges[PLUG_MAX];
static int plug_n;

/* the hosted shell image's LOAD sha -- the identity every plugin must
 * have been linked against (plugsyms bakes the shell's ABSOLUTE symbol
 * addresses into the plugin, so under any other shell its global
 * accesses poke the wrong memory; the corruption is silent and
 * layout-dependent, hence a HARD gate, not a warning) */
void qosp_sha256(const unsigned char *msg, uint64_t n, unsigned char out[32]); /* sha256.c */
static char g_shell_sha[72];
static int span_is(qos_span_t a, const char *z) {
  uint64_t n = strlen(z);
  return a.n == n && !memcmp(a.p, z, n);
}
int64_t qosp_load_plugin(const qos_plugin_t *pl, char *err, uint64_t errcap) {
  if (plug_n >= PLUG_MAX) {
    snprintf(err, errcap, "plugin registry full");
    return -1;
  }
  int idn = (int)pl->id.n;
  const char *id = (const char *)pl->id.p;
  /* The enforcer's checks, over fields the app read from the archive: is
   * this plugin from the same build as the image it is joining?  They
   * catch a stale matched set, not a hostile app -- one address space has
   * no such boundary.  An unstamped plugin is a pre-stamp archive. */
  char want[24];
  snprintf(want, sizeof want, "%u.%u", (unsigned)QOS_ABI_VERSION, (unsigned)QOSP_CODEGEN_REV);
  if (pl->abi.n && !span_is(pl->abi, want)) {
    snprintf(err, errcap, "abi mismatch: plugin %.*s built for %.*s, shell wants "
             "%s -- rebuild as a matched set", idn, id, (int)pl->abi.n, (const char *)pl->abi.p, want);
    return -1;
  }
  if (pl->shell.n && g_shell_sha[0] && !span_is(pl->shell, g_shell_sha)) {
    snprintf(err, errcap, "matched-set REFUSED: plugin %.*s was linked against "
             "shell %.12s... but this shell is %.12s... -- repackage against "
             "the running image", idn, id, (const char *)pl->shell.p, g_shell_sha);
    return -1;
  }
  if (!pl->shell.n)
    fprintf(stderr, "[qos] warning: plugin %.*s carries no shell stamp "
            "(pre-stamp archive); the matched-set gate cannot protect it\n", idn, id);
  /* the image is what its LOAD section says it is, or it does not load */
  if (pl->sha.n) {
    unsigned char d[32];
    char hex[65];
    qosp_sha256(pl->img.p, pl->img.n, d);
    for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", d[i]);
    if (!span_is(pl->sha, hex)) {
      snprintf(err, errcap, "plugin %.*s: IMAGE sha256 mismatch (corrupt archive)", idn, id);
      return -1;
    }
  }
  /* the archive DECLARES its span (LOAD base/memsz, read by the app with
   * mods/qaimg.fpr).  Overlap-check the declared span first, place second: a
   * bad plugin is refused before a byte lands. */
  fpr_qaimg_t qp = {pl->base, pl->entry, pl->execsz, pl->rwoff, pl->memsz};
  if (qp.memsz == 0) {
    snprintf(err, errcap, "plugin LOAD section unusable");
    return -1;
  }
  uintptr_t pg = (uintptr_t)getpagesize();
  uintptr_t imlo = qp.base & ~(pg - 1);
  uintptr_t imhi = (qp.base + qp.memsz + pg - 1) & ~(pg - 1);
  for (int i = 0; i < plug_n; i++)
    if (imlo < plug_ranges[i].hi && imhi > plug_ranges[i].lo) {
      snprintf(err, errcap, "plugin overlaps an already-loaded image "
               "(link each app at its own sub-slot base)");
        return -1;
    }
  fpr_elf_load_t ld = fpr_qaimg_place(&qp, pl->img.p, pl->img.n,
                                      (void *)QOS_PLUG_BASE, QOS_PLUG_SIZE);
  if (!ld.ok) {
    snprintf(err, errcap, "plugin image: %s", ld.err);
    return -1;
  }
  uintptr_t xend = ((uintptr_t)ld.exec_end + pg - 1) & ~(pg - 1);
  if (ld.exec_end && (uintptr_t)ld.rw_start < xend) {
    snprintf(err, errcap, "plugin not page-separated (exec_end=%p rw=%p)",
             ld.exec_end, ld.rw_start);
    return -1;
  }
  if (mprotect((void *)imlo, xend - imlo, PROT_READ | PROT_EXEC)) {
    snprintf(err, errcap, "plugin mprotect: %s", strerror(errno));
    return -1;
  }
  __builtin___clear_cache((char *)imlo, (char *)ld.image_end);
  plug_ranges[plug_n].lo = imlo;
  plug_ranges[plug_n].hi = imhi;
  plug_n++;
  qos_hostlog("[qosp] plugin %.*s (%llu B): table at %p, image %#lx-%#lx",
              idn, id, (unsigned long long)pl->img.n, ld.entry, (unsigned long)imlo,
              (unsigned long)imhi);
  return (int64_t)(uintptr_t)ld.entry;
}

/* v12: no grow callback.  The app owns the arena past its image and
 * runs its own buddy behind its memory actor (docs/MEMORY.md); the
 * host's buddy, the grow mutex, and the grow trace went with it. */

/* ---- multi-hart (ABI v2) --------------------------------------------
 * The TLS borrow block: one per hart THREAD, host __thread -- the app
 * indexes it through the thread pointer plus the constant displacement
 * published in the boot record (static TLS: same in every thread).
 * Layout is pinned by qos_abi.h: {hart, a6, a7} at 0/8/16. */
struct qosp_tls { void *hart; uint64_t a6, a7; };
static __thread struct qosp_tls qosp_tls_blk;
static uint64_t qosp_tls_off(void) {
  return (uint64_t)((char *)&qosp_tls_blk -
                    (char *)__builtin_thread_pointer());
}

/* start_hart: pthread_create done host-side (the app is freestanding).
 * The trampoline touches the borrow block (forcing nothing -- static
 * TLS always exists -- but documenting the dependency) and calls the
 * app's hart entry; the thread returns when the app world ends
 * (fpr_process_done fails every hart loop), and main joins them all
 * after the entry returns. */
#define QOSP_MAXHARTS 64
static pthread_t hart_threads[QOSP_MAXHARTS];
static unsigned hart_nthreads;
struct hart_arg { uint64_t idx; void (*fn)(uint64_t); };
void hal_fault_altstack(void); /* fprisc/hal/posix/hal.c: this thread's alternate signal stack */
static void *hart_tramp(void *p) {
  struct hart_arg a = *(struct hart_arg *)p;
  free(p);
  qosp_tls_blk.hart = 0; /* the app's fpr_set_tp fills it */
  hal_fault_altstack();  /* an alternate signal stack is per thread */
  a.fn(a.idx);
  return 0;
}
static int start_hart_cb(uint64_t idx, void (*fn)(uint64_t)) {
  if (hart_nthreads >= QOSP_MAXHARTS) return -1;
  struct hart_arg *a = malloc(sizeof *a);
  if (!a) return -1;
  a->idx = idx; a->fn = fn;
  if (pthread_create(&hart_threads[hart_nthreads], 0, hart_tramp, a)) {
    free(a);
    return -1;
  }
  hart_nthreads++;
  return 0;
}
static void join_harts(void) {
  for (unsigned i = 0; i < hart_nthreads; i++)
    pthread_join(hart_threads[i], 0);
  hart_nthreads = 0;
}

/* the resolved live-hart count: FPR_HARTS env wins, else the online
 * core count -- "auto detect the host's n cores and spawn that many
 * pthread harts".  The app clamps again to its own compile-time cap. */
static uint64_t resolve_nharts(void) {
  const char *e = getenv("FPR_HARTS");
  long n = 0;
  if (e && *e) n = strtol(e, 0, 10);
  if (n <= 0) n = sysconf(_SC_NPROCESSORS_ONLN);
  if (n < 1) n = 1;
  if (n > QOSP_MAXHARTS) n = QOSP_MAXHARTS;
  return (uint64_t)n;
}

/* fprisc/hal/posix/hal.c, linked here: the guard's check and its last words */
int hal_stack_guard_hit(void *lo, uint64_t size, void *addr);
void hal_stack_overflow_die(uint64_t id, uint64_t size);
extern void *(*qosp_app_stack_query)(uint64_t *id, uint64_t *size); /* haltab.c */
static int g_in_app; /* x28 / the TLS hart slot are the APP's while this is set */

static void bus_handler(int sig, siginfo_t *info, void *vctx) {
  /* first: did an actor run off its stack?  The app's runtime knows which
   * one is running on this hart; this file is built -ffixed-x28 on arm64,
   * so the app's hart register is still what the faulting code left. */
  if (g_in_app && qosp_app_stack_query) {
    uint64_t id = 0, size = 0;
    void *lo = qosp_app_stack_query(&id, &size);
    if (hal_stack_guard_hit(lo, size, info->si_addr)) hal_stack_overflow_die(id, size);
  }
  /* Diagnostic only: report where the app faulted, then die.  The arena
   * is plain rw with an r-x code prefix (see stage 2), so any fault here
   * is a real bug in the app or the loader, not a protection artifact. */
  ucontext_t *uc = (ucontext_t *)vctx;
#ifdef __APPLE__
  uintptr_t pc = uc ? uc->uc_mcontext->__ss.__pc : 0;
#else
  uintptr_t pc = 0; (void)uc;
#endif
  void *addr = info ? info->si_addr : 0;
  int in_image = (pc >= QOS_SLOT_BASE && pc < QOS_SLOT_BASE + QOS_SLOT_SIZE);
  /* DELIBERATELY bare stderr: a fault handler must not take the
   * app's locks (the fault may BE inside fpr_logput); the app-side
   * error ring + #24 persist already cover app panics. */
  fprintf(stderr, "qosp: fatal %s: addr=%p pc=%#lx in_image=%d\n",
          sig == SIGBUS ? "SIGBUS" : "SIGSEGV", addr, (unsigned long)pc,
          in_image);
  fflush(stderr);
  _exit(139);
}

/* ====================================================================
 * THE HOST'S PRIMITIVES.  qosp is an FP-RISC program (portable/qosp.fpr):
 * it reads the archive, interprets the manifest, gates the abi, verifies
 * the image, asks for permissions and builds the capability blob -- with
 * the same modules the kernel launches with.  What is left here is what
 * only C on this OS can do: map memory at an address, hash, place and
 * protect an image, and hand the machine to it.  Each is declared in
 * qosp.fpr as a signature with no definition.
 * ==================================================================== */
extern int fpr_posix_argc;
extern char **fpr_posix_argv;

static V res_ok_str(const char *s2, uw n) { return fpr_mkresultn(0, s2, n); }
static V res_err(const char *msg) { return fpr_mkresultn(1, msg, strlen(msg)); }
static const str_t *arg_str(V v, const char *who) {
  if (ISINT(v) || TID(v) != T_STR) fpr_cpanic(who);
  return (const str_t *)v;
}

/* Host.log : String -> Unit -- one /logs/host line */
static V h_log(V sv) {
  const str_t *t = arg_str(sv, "Host.log: expected a String");
  qos_hostlog("%.*s", (int)t->len, (const char *)t->bytes);
  return (V)&fpr_unit;
}
FPR_FN(fpr_g_Host_x2elog, h_log, 1);

/* Host.abi : Unit -> String -- "<QOS_ABI_VERSION>.<codegenRev>", what this
 * host was built against; whether an archive's stamp is acceptable is
 * qosp.fpr's call */
static V h_abi(V u) {
  (void)u;
  char want[24];
  int n = snprintf(want, sizeof want, "%u.%u", (unsigned)QOS_ABI_VERSION, (unsigned)QOSP_CODEGEN_REV);
  return (V)fpr_mkstr((const uint8_t *)want, (uw)n);
}
FPR_FN(fpr_g_Host_x2eabi, h_abi, 1);

/* Host.sha256 : String -> String -- lower-case hex */
static V h_sha256(V sv) {
  const str_t *t = arg_str(sv, "Host.sha256: expected a String");
  unsigned char d[32];
  char hex[64];
  qosp_sha256(t->bytes, t->len, d);
  for (int i = 0; i < 32; i++) {
    hex[2 * i] = "0123456789abcdef"[d[i] >> 4];
    hex[2 * i + 1] = "0123456789abcdef"[d[i] & 15];
  }
  return (V)fpr_mkstr((const uint8_t *)hex, 64);
}
FPR_FN(fpr_g_Host_x2esha256, h_sha256, 1);

/* Host.init : Bool -> Result String String -- fault reporting, and the
 * arena at its published address.  Ok "" | Err reason. */
static V h_init(V tracev) {
  g_trace = !ISINT(tracev) && ((hdr_t *)tracev)->var != 0;
  if (getenv("QOSP_TRACE")) g_trace = 1;
  struct sigaction sa = {0};
  sa.sa_sigaction = bus_handler;
  sigemptyset(&sa.sa_mask);
  sa.sa_flags = SA_SIGINFO | SA_ONSTACK; /* the faulting stack may be the exhausted one */
  sigaction(SIGBUS, &sa, NULL);
  sigaction(SIGSEGV, &sa, NULL);
  TRACE("stage 1 (initializer): mapping arena at %#lx (+%lu MiB)\n",
        QOS_ARENA_BASE, QOS_ARENA_SIZE >> 20);
  void *arena = mmap((void *)QOS_ARENA_BASE, QOS_ARENA_SIZE, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  if (arena != (void *)QOS_ARENA_BASE) {
    if (arena != MAP_FAILED) munmap(arena, QOS_ARENA_SIZE);
#ifdef __APPLE__
    /* arm64 macOS forces PIE, and occasionally slides this host across the
     * fixed app arena.  A new exec gets a fresh slide; never MAP_FIXED over
     * the live image. */
    const char *retry_s = getenv("QOSP_ARENA_REEXEC");
    int retry = retry_s ? atoi(retry_s) : 0;
    if (retry < 8) {
      char next[16];
      snprintf(next, sizeof next, "%d", retry + 1);
      setenv("QOSP_ARENA_REEXEC", next, 1);
      execvp(fpr_posix_argv[0], fpr_posix_argv);
    }
#endif
    return res_err("cannot map the arena at its published address (ASLR collision or RWX "
                   "policy) -- the app image is linked there, so there is no fallback");
  }
#ifdef __APPLE__
  unsetenv("QOSP_ARENA_REEXEC");
#endif
  return res_ok_str("", 0);
}
FPR_FN(fpr_g_Host_x2einit, h_init, 1);

/* Host.loadImage : String -> String -> String -> List Int -> Result String String
 * the archive's path (assets resolve beside it), the sha its LOAD section
 * claims (this image's identity: every plugin must have been linked against
 * it), its IMAGE section and LOAD's numbers as mods/qaimg.fpr read them:
 * place the image in the slot and publish its code r-x. */
static fpr_elf_load_t g_ld;
static V h_load_image(V pathv, V shav, V imgv, V numsv) {
  const str_t *path = arg_str(pathv, "Host.loadImage: path must be a String");
  const str_t *sha = arg_str(shav, "Host.loadImage: sha must be a String");
  const str_t *img = arg_str(imgv, "Host.loadImage: IMAGE must be a String");
  uw n[5];
  if (!fpr_list_ints(numsv, n, 5)) fpr_cpanic("Host.loadImage: nums must be [base, entry, execsz, rwoff, memsz]");
  char *cpath = malloc(path->len + 1); /* qos_snd keeps the pointer */
  if (!cpath) return res_err("out of memory");
  memcpy(cpath, path->bytes, path->len);
  cpath[path->len] = 0;
  qos_snd_set_assets(cpath); /* music and other assets resolve beside the .qa */
  if (sha->len >= sizeof g_shell_sha) return res_err("sha too long");
  memcpy(g_shell_sha, sha->bytes, sha->len);
  g_shell_sha[sha->len] = 0;

  fpr_qaimg_t q = {n[0], n[1], n[2], n[3], n[4]};
  fpr_elf_load_t ld = fpr_qaimg_place(&q, img->bytes, img->len, (void *)QOS_SLOT_BASE, QOS_ARENA_SIZE);
  if (!ld.ok) return res_err(ld.err);
  /* Publish the code: the arena is one rw anonymous mapping, and a page is
   * never writable and executable at once, so flip just the executable
   * prefix (the PF_X PT_LOADs) to r-x and leave the rest rw.  The linker
   * script puts .text first and the RW segment on its own 64 KiB-aligned
   * page, so the host-page round-up never captures a writable byte.  This
   * runs on EVERY host: a plain rw mapping is not executable on Linux
   * either.  The icache clear is needed on any arm64 host. */
  uintptr_t pg = (uintptr_t)getpagesize();
  uintptr_t xend = ((uintptr_t)ld.exec_end + pg - 1) & ~(pg - 1);
  if (xend <= (uintptr_t)QOS_SLOT_BASE || ld.exec_end == 0)
    return res_err("image has no executable segment");
  if ((uintptr_t)ld.rw_start < xend)
    return res_err("executable pages would capture writable image data -- relink "
                   "with page-separated segments");
  if (mprotect((void *)QOS_SLOT_BASE, xend - QOS_SLOT_BASE, PROT_READ | PROT_EXEC))
    return res_err("mprotect(code, r-x) failed");
  TRACE("stage 2: image [%#lx..%p), entry %p, code r-x to %#lx\n",
        QOS_SLOT_BASE, ld.image_end, ld.entry, (unsigned long)xend);
  __builtin___clear_cache((char *)QOS_SLOT_BASE, (char *)ld.image_end);
  g_ld = ld;
  return res_ok_str("", 0);
}
FPR_FN(fpr_g_Host_x2eloadImage, h_load_image, 4);

/* the app's entry is freestanding code that keeps ITS hart in x28 and does
 * not restore ours; this program's own hart lives there too */
static int64_t enter_app(qos_app_entry_t entry, qos_boot_t *boot, char *result, uint64_t cap) {
#if defined(__aarch64__)
  volatile uint64_t mine;
  __asm__ volatile("mov x9, x28\n" "str x9, %0" : "=*m"(mine) : : "x9");
  int64_t rc = entry(boot, result, cap);
  __asm__ volatile("ldr x9, %0\n" "mov x28, x9" : : "*m"(mine) : "x9");
  return rc;
#else
  return entry(boot, result, cap);
#endif
}

/* Host.run : String -> String -> String -> Result String String
 * the app's id, its display name and its capability blob: bind the store,
 * build the boot record, start the harts and enter the loaded image.
 * Ok <main's result> | Err reason. */
static V h_run(V idv, V namev, V capsv) {
  const str_t *id = arg_str(idv, "Host.run: id must be a String");
  const str_t *name = arg_str(namev, "Host.run: name must be a String");
  const str_t *capss = arg_str(capsv, "Host.run: caps must be a String");
  if (!g_ld.ok) return res_err("Host.run before Host.loadImage");
  /* the app reads these for as long as it runs: out of this runtime's heap */
  char *cid = malloc(id->len + 1), *caps = malloc(capss->len + 1);
  if (!cid || !caps) return res_err("out of memory");
  memcpy(cid, id->bytes, id->len); cid[id->len] = 0;
  memcpy(caps, capss->bytes, capss->len); caps[capss->len] = 0;
  qosp_store_bind(cid);

  uint64_t arena_base = ((uint64_t)g_ld.image_end + 15) & ~15ull;
  uint64_t arena_size = (QOS_ARENA_BASE + QOS_ARENA_SIZE) - arena_base;
  qos_boot_t boot = {
      .abi_version = QOS_ABI_VERSION,
      .hal = qosp_hal_table(),
      .heap_base = 0, /* v12: the app carves its own first slab */
      .heap_size = 0,
      .grow = 0,      /* v12: retired -- the arena is the app's */
      .caps = (const unsigned char *)caps,
      .caps_len = capss->len,
      .syscall_fn = qosp_store_call,
      .tls_off = qosp_tls_off(),
      .arena_base = (void *)arena_base,
      .arena_size = arena_size,
  };
  qosp_hal_set_smp(resolve_nharts(), start_hart_cb);
  /* the guaranteed first /logs/host line: which host, which app, how
   * many harts -- pends here, replays into the ring at registration */
  qos_hostlog("qosp: hosting %.*s (%" PRIu64 " harts, abi v%u)",
              (int)(name->len ? name->len : id->len),
              (const char *)(name->len ? name->bytes : id->bytes),
              resolve_nharts(), (unsigned)QOS_ABI_VERSION);
  TRACE("stage 3: entering the app (arena %#" PRIx64 " +%" PRIu64 " MiB, tls_off %" PRId64 ")\n",
        arena_base, arena_size >> 20, (int64_t)boot.tls_off);
  static char result[64 * 1024]; /* the entry ABI's buffer (docs/BOUNDS.md) */
  fflush(stdout);
  g_in_app = 1;
  int64_t rc = enter_app((qos_app_entry_t)g_ld.entry, &boot, result, sizeof result);
  g_in_app = 0;
  join_harts(); /* every hart loop exited through fpr_process_done */
  if (rc) return res_err("the app entry rejected the boot record (abi mismatch?)");
  return res_ok_str(result, strlen(result));
}
FPR_FN(fpr_g_Host_x2erun, h_run, 3);
