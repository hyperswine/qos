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
 *     compulsory: any denial refuses the launch, docs/2026-07-19-QA-FORMAT.md);
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

/* ---- publishing a plugin's code (syscall tag 4, qos_abi.h) ------------
 * The APP places a plugin: it takes a block from its own buddy, copies the
 * image in, moves its address words and completes its imports by name from
 * its own export table (qos/appside/plugimg.c,
 * docs/2026-10-01-IMPORT-TABLE.md).  What only the host can do is make the
 * code executable: the arena is one rw mapping, and a page is never
 * writable and executable at once.  So the host checks what it is asked to
 * publish -- built for this ABI, the bytes the archive claims, inside the
 * app's arena, its code on pages of its own -- flips the code to r-x,
 * clears the instruction cache, and hands back the module table's address.
 * Nothing about a plugin is tied to an address or to one app build. */
void qosp_sha256(const unsigned char *msg, uint64_t n, unsigned char out[32]); /* sha256.c */
static int span_is(qos_span_t a, const char *z) {
  uint64_t n = strlen(z);
  return a.n == n && !memcmp(a.p, z, n);
}
static uint64_t g_arena_size; /* 0: could not reserve address space for the arena */
static uintptr_t g_arena_base; /* where it landed: the published address when free, else anywhere (the image is relocatable) */
static fpr_elf_load_t g_ld;    /* the placed image (Host.loadImage) */
static uintptr_t g_img_base;   /* where it was placed: the arena's start */
int64_t qosp_load_plugin(const qos_plugin_t *pl, char *err, uint64_t errcap) {
  int idn = (int)pl->id.n;
  const char *id = (const char *)pl->id.p;
  char want[24];
  snprintf(want, sizeof want, "%u.%u", (unsigned)QOS_ABI_VERSION, (unsigned)QOSP_CODEGEN_REV);
  if (!span_is(pl->abi, want)) {
    snprintf(err, errcap, "abi mismatch: plugin %.*s built for %.*s, this host is %s "
             "-- rebuild the plugin", idn, id, (int)pl->abi.n, (const char *)pl->abi.p, want);
    return -1;
  }
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
  /* ...and its relocations and imports are what LOAD says they are */
  if (pl->relsha.n) {
    unsigned char d[32];
    char hex[65];
    unsigned char *both = malloc(pl->rel.n + pl->imp.n + 1);
    if (!both) { snprintf(err, errcap, "out of memory"); return -1; }
    memcpy(both, pl->rel.p, pl->rel.n);
    memcpy(both + pl->rel.n, pl->imp.p, pl->imp.n);
    qosp_sha256(both, pl->rel.n + pl->imp.n, d);
    free(both);
    for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", d[i]);
    if (!span_is(pl->relsha, hex)) {
      snprintf(err, errcap, "plugin %.*s: RELOC sha256 mismatch (corrupt archive)", idn, id);
      return -1;
    }
  }
  uintptr_t pg = (uintptr_t)getpagesize();
  uintptr_t lo = (uintptr_t)pl->base, hi = lo + pl->memsz;
  uintptr_t alo = g_arena_base, ahi = alo + g_arena_size;
  if (pl->memsz == 0 || hi < lo || lo < alo || hi > ahi) {
    snprintf(err, errcap, "plugin %.*s: not placed inside the app's arena", idn, id);
    return -1;
  }
  if (lo & (pg - 1)) {
    snprintf(err, errcap, "plugin %.*s: placed off a page boundary", idn, id);
    return -1;
  }
  uintptr_t xend = (lo + pl->execsz + pg - 1) & ~(pg - 1);
  if (pl->execsz == 0 || pl->entry >= pl->memsz || (pl->rwoff < pl->memsz && lo + pl->rwoff < xend)) {
    snprintf(err, errcap, "plugin %.*s: its code and writable data share a page", idn, id);
    return -1;
  }
  if (mprotect((void *)lo, xend - lo, PROT_READ | PROT_EXEC)) {
    snprintf(err, errcap, "plugin mprotect: %s", strerror(errno));
    return -1;
  }
  __builtin___clear_cache((char *)lo, (char *)hi);
  qos_hostlog("[qosp] plugin %.*s (%llu B): published at %#lx-%#lx, table at %#lx",
              idn, id, (unsigned long long)pl->img.n, (unsigned long)lo,
              (unsigned long)hi, (unsigned long)(lo + pl->entry));
  return (int64_t)(lo + pl->entry);
}

/* syscall tag 8: the image's process ended and the app frees its block;
 * undo the r-x so the buddy can hand the pages out as heap again.  The
 * range is checked the way a publish is (inside the arena, page aligned);
 * the host keeps no ledger of published ranges, the app's image map is it. */
int64_t qosp_unload_plugin(const qos_unload_t *u, char *err, uint64_t errcap) {
  uintptr_t pg = (uintptr_t)getpagesize();
  uintptr_t lo = (uintptr_t)u->base;
  uintptr_t xend = (lo + u->execsz + pg - 1) & ~(pg - 1);
  uintptr_t alo = g_arena_base, ahi = alo + g_arena_size;
  if (u->execsz == 0 || xend < lo || lo < alo || xend > ahi || (lo & (pg - 1))) {
    snprintf(err, errcap, "unload: not a published plugin range");
    return -1;
  }
  if (mprotect((void *)lo, xend - lo, PROT_READ | PROT_WRITE)) {
    snprintf(err, errcap, "unload mprotect: %s", strerror(errno));
    return -1;
  }
  qos_hostlog("[qosp] plugin at %#lx-%#lx: its process ended, pages writable again",
              (unsigned long)lo, (unsigned long)xend);
  return 0;
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
void hal_fault_altstack(void); /* fprisc/machine/posix/hal.c: this thread's alternate signal stack */
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

/* fprisc/machine/posix/hal.c, linked here: the guard's check and its last words */
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
  int in_image = (g_img_base && pc >= g_img_base && pc < (uintptr_t)g_ld.image_end);
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
/* The arena: address space RESERVED at the address app images are linked
 * for, committed by the OS as the app touches it -- so it has no size to
 * choose (it was ARENA_MB, 2048, and had to agree with a number linked into
 * every app).  Made before this host's own heap is reserved, which would
 * otherwise be free to land here (machine/posix hal_heap_before_reserve).
 * QOSP_ARENA_MB caps it for a run: a test of exhaustion. */
void hal_heap_before_reserve(void) {
  uw max = QOS_ARENA_MAX, min = QOS_ARENA_MIN, got = 0;
  const char *cap = getenv("QOSP_ARENA_MB");
  if (cap && atol(cap) > 0) max = min = (uw)atol(cap) << 20;
  /* the published address first (a hint: nothing is linked to it any more),
   * else anywhere the OS has the room -- the app image is relocatable
   * (2026-10-02; it was linked at QOS_SLOT_BASE, and a host whose ASLR slide
   * landed there had to re-exec itself) */
  void *p = getenv("QOSP_ARENA_ANYWHERE") ? 0 : fpr_heap_reserve((void *)QOS_ARENA_BASE, max, min, &got);
  if (!p) p = fpr_heap_reserve(0, max, min, &got); /* QOSP_ARENA_ANYWHERE: the fallback on purpose (a test of the relocation) */
  g_arena_size = p ? got : 0;
  g_arena_base = (uintptr_t)p;
}

static V h_init(V tracev) {
  g_trace = !ISINT(tracev) && ((hdr_t *)tracev)->var != 0;
  if (getenv("QOSP_TRACE")) g_trace = 1;
  struct sigaction sa = {0};
  sa.sa_sigaction = bus_handler;
  sigemptyset(&sa.sa_mask);
  sa.sa_flags = SA_SIGINFO | SA_ONSTACK; /* the faulting stack may be the exhausted one */
  sigaction(SIGBUS, &sa, NULL);
  sigaction(SIGSEGV, &sa, NULL);
  TRACE("stage 1 (initializer): arena at %#lx, %lu MiB of address space reserved\n",
        (unsigned long)g_arena_base, (unsigned long)(g_arena_size >> 20));
  if (!g_arena_size)
    return res_err("cannot reserve address space for the arena (QOSP_ARENA_MB caps it; a strict "
                   "overcommit or RWX policy refuses it)");
  return res_ok_str("", 0);
}
FPR_FN(fpr_g_Host_x2einit, h_init, 1);

/* Host.loadImage : String -> String -> String -> List Int -> String -> Result String String
 * the archive's path (assets resolve beside it), the sha its LOAD section
 * claims, its IMAGE section, LOAD's numbers as mods/qaimg.fpr read them, and
 * its RELOC section: place the image at the arena's start, move its address
 * words there, and publish its code r-x.  A fixed image (base != 0) is
 * refused unless the arena happens to be where it was linked. */
static V h_load_image(V pathv, V shav, V imgv, V numsv, V relv) {
  const str_t *path = arg_str(pathv, "Host.loadImage: path must be a String");
  const str_t *sha = arg_str(shav, "Host.loadImage: sha must be a String");
  const str_t *img = arg_str(imgv, "Host.loadImage: IMAGE must be a String");
  const str_t *rel = arg_str(relv, "Host.loadImage: RELOC must be a String (empty for a fixed image)");
  uw n[5];
  if (!fpr_list_ints(numsv, n, 5)) fpr_cpanic("Host.loadImage: nums must be [base, entry, execsz, rwoff, memsz]");
  char *cpath = malloc(path->len + 1); /* qos_snd keeps the pointer */
  if (!cpath) return res_err("out of memory");
  memcpy(cpath, path->bytes, path->len);
  cpath[path->len] = 0;
  qos_snd_set_assets(cpath); /* music and other assets resolve beside the .qa */
  (void)sha; /* plugins no longer need the shell's identity: they bind by name */

  uintptr_t dst = n[0] ? (uintptr_t)n[0] : ((g_arena_base + 0xFFFF) & ~(uintptr_t)0xFFFF);
  if (n[0] && (uintptr_t)n[0] != g_arena_base)
    return res_err("a fixed image linked for another address than the arena landed at -- rebuild it (relocatable)");
  if (!n[0] && rel->len == 0) return res_err("a relocatable image without a RELOC section");
  uintptr_t room = (g_arena_base + g_arena_size) - dst;
  fpr_qaimg_t q = {dst, n[1], n[2], n[3], n[4]};
  fpr_elf_load_t ld = fpr_qaimg_place(&q, img->bytes, img->len, (void *)dst, room < QOS_SLOT_SIZE ? room : QOS_SLOT_SIZE);
  if (!ld.ok) return res_err(ld.err);
  if (!n[0]) {
    const char *bad = fpr_qaimg_relocate((unsigned char *)dst, img->len, rel->bytes, rel->len);
    if (bad) return res_err(bad);
  }
  g_img_base = dst;
  /* Publish the code: the arena is one rw anonymous mapping, and a page is
   * never writable and executable at once, so flip just the executable
   * prefix (the PF_X PT_LOADs) to r-x and leave the rest rw.  The linker
   * script puts .text first and the RW segment on its own 64 KiB-aligned
   * page, so the host-page round-up never captures a writable byte.  This
   * runs on EVERY host: a plain rw mapping is not executable on Linux
   * either.  The icache clear is needed on any arm64 host. */
  uintptr_t pg = (uintptr_t)getpagesize();
  uintptr_t xend = ((uintptr_t)ld.exec_end + pg - 1) & ~(pg - 1);
  if (xend <= dst || ld.exec_end == 0)
    return res_err("image has no executable segment");
  if ((uintptr_t)ld.rw_start < xend)
    return res_err("executable pages would capture writable image data -- relink "
                   "with page-separated segments");
  if (mprotect((void *)dst, xend - dst, PROT_READ | PROT_EXEC))
    return res_err("mprotect(code, r-x) failed");
  TRACE("stage 2: image [%#lx..%p), entry %p, code r-x to %#lx\n",
        (unsigned long)dst, ld.image_end, ld.entry, (unsigned long)xend);
  __builtin___clear_cache((char *)dst, (char *)ld.image_end);
  g_ld = ld;
  return res_ok_str("", 0);
}
FPR_FN(fpr_g_Host_x2eloadImage, h_load_image, 5);

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
  uint64_t arena_size = (g_arena_base + g_arena_size) - arena_base;
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
  static char result[64 * 1024]; /* the entry ABI's buffer (docs/2026-09-19-BOUNDS.md) */
  fflush(stdout);
  g_in_app = 1;
  int64_t rc = enter_app((qos_app_entry_t)g_ld.entry, &boot, result, sizeof result);
  g_in_app = 0;
  join_harts(); /* every hart loop exited through fpr_process_done */
  if (rc) return res_err("the app entry rejected the boot record (abi mismatch?)");
  return res_ok_str(result, strlen(result));
}
FPR_FN(fpr_g_Host_x2erun, h_run, 3);
