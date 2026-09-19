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
#include "qa.h"

/* ---- the ABI stamp (kills the apps-qa desync class) -----------------
 * fprc stamps `abi = "<QOS_ABI_VERSION>.<codegenRev>"` into every
 * manifest at pack time; a mismatch used to be an undiagnosable crash
 * mid-run.  One honest line instead.  The rev here must track
 * Codegen.hs codegenRev (or be passed as -DQOSP_CODEGEN_REV). */
#ifndef QOSP_CODEGEN_REV
#define QOSP_CODEGEN_REV 7
#endif
static int abi_gate(qa_t *); /* defined with perm_gate below */
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

/* gfx.c (compiled into a GFX=1 qosp) faults through fpr_cpanic; in the
 * HOST image that is a loud exit, the host idiom for the same honesty
 * the co-compiled HAL expresses with a panic. */
__attribute__((noreturn)) void fpr_cpanic(const char *msg) {
  qos_hostlog("qosp: %s", msg);
  exit(1);
}
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
static char g_shell_sha[72];
static void load_sha_hex(const unsigned char *load, uint64_t n, char *out,
                         uint64_t cap) {
  out[0] = 0;
  for (uint64_t i = 0; i + 4 < n; i++)
    if (!memcmp(load + i, "sha ", 4) && (i == 0 || load[i - 1] == '\n')) {
      uint64_t j = i + 4, k = 0;
      while (j < n && load[j] != '\n' && k + 1 < cap) out[k++] = (char)load[j++];
      out[k] = 0;
      return;
    }
}
int64_t qosp_load_plugin_bytes(const char *bytes, uint64_t len, char *err,
                               uint64_t errcap) {
  if (plug_n >= PLUG_MAX) {
    snprintf(err, errcap, "plugin registry full");
    return -1;
  }
  if (len < 5 || memcmp(bytes, "QAR2\n", 5)) {
    snprintf(err, errcap,
             "payload is not a QAR2 archive (attachQa takes the .qa BYTES "
             "now -- read apps/<id>.qa off the disk first)");
    return -1;
  }
  qa_t qa;
  if (qa_parse((const unsigned char *)bytes, len, &qa)) {
    snprintf(err, errcap, "malformed .qa payload (see stderr)");
    return -1;
  }
  if (abi_gate(&qa)) {
    snprintf(err, errcap, "abi mismatch: plugin %s built for %s, shell wants "
             "%u.%u -- rebuild as a matched set", qa.id,
             qa.abi[0] ? qa.abi : "(unstamped)",
             (unsigned)QOS_ABI_VERSION, (unsigned)QOSP_CODEGEN_REV);
    qa_free(&qa);
    return -1;
  }
  if (qa.shell[0] && g_shell_sha[0] && strcmp(qa.shell, g_shell_sha) != 0) {
    snprintf(err, errcap, "matched-set REFUSED: plugin %s was linked against "
             "shell %.12s... but this shell is %.12s... -- repackage against "
             "the running image", qa.id, qa.shell, g_shell_sha);
    qa_free(&qa);
    return -1;
  }
  if (!qa.shell[0])
    fprintf(stderr, "[qos] warning: plugin %s carries no shell stamp "
            "(pre-stamp archive); the matched-set gate cannot protect it\n",
            qa.id);
  /* the archive DECLARES its span (LOAD base/memsz) -- no more
   * recovering it from segment high-water marks and 4 MiB masks.
   * Overlap-check the declared span first, load second: a bad plugin
   * is refused before a byte lands. */
  fpr_qaimg_t qp;
  if (!fpr_qaimg_params(qa.load, qa.load_len, &qp) || qp.memsz == 0) {
    snprintf(err, errcap, "plugin LOAD section unusable");
    qa_free(&qa);
    return -1;
  }
  uintptr_t pg = (uintptr_t)getpagesize();
  uintptr_t imlo = qp.base & ~(pg - 1);
  uintptr_t imhi = (qp.base + qp.memsz + pg - 1) & ~(pg - 1);
  for (int i = 0; i < plug_n; i++)
    if (imlo < plug_ranges[i].hi && imhi > plug_ranges[i].lo) {
      snprintf(err, errcap, "plugin overlaps an already-loaded image "
               "(link each app at its own sub-slot base)");
      qa_free(&qa);
      return -1;
    }
  fpr_elf_load_t ld = fpr_qaimg_load(qa.load, qa.load_len, qa.img, qa.img_len,
                                     (void *)QOS_PLUG_BASE, QOS_PLUG_SIZE);
  if (!ld.ok) {
    snprintf(err, errcap, "plugin image: %s", ld.err);
    qa_free(&qa);
    return -1;
  }
  uintptr_t xend = ((uintptr_t)ld.exec_end + pg - 1) & ~(pg - 1);
  if (ld.exec_end && (uintptr_t)ld.rw_start < xend) {
    snprintf(err, errcap, "plugin not page-separated (exec_end=%p rw=%p)",
             ld.exec_end, ld.rw_start);
    qa_free(&qa);
    return -1;
  }
  if (mprotect((void *)imlo, xend - imlo, PROT_READ | PROT_EXEC)) {
    snprintf(err, errcap, "plugin mprotect: %s", strerror(errno));
    qa_free(&qa);
    return -1;
  }
  __builtin___clear_cache((char *)imlo, (char *)ld.image_end);
  plug_ranges[plug_n].lo = imlo;
  plug_ranges[plug_n].hi = imhi;
  plug_n++;
  qos_hostlog("[qosp] plugin %s (%llu B): table at %p, image %#lx-%#lx",
              qa.id, (unsigned long long)len, ld.entry, (unsigned long)imlo,
              (unsigned long)imhi);
  qa_free(&qa); /* the IMAGE bytes are in the window now */
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
static void *hart_tramp(void *p) {
  struct hart_arg a = *(struct hart_arg *)p;
  free(p);
  qosp_tls_blk.hart = 0; /* the app's fpr_set_tp fills it */
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

/* abi_gate: see the stamp comment at the top.  Empty stamp = pre-stamp
 * archive, accepted with a warning (transition path). */
static int abi_gate(qa_t *qa) {
  char want[24];
  snprintf(want, sizeof want, "%u.%u", (unsigned)QOS_ABI_VERSION,
           (unsigned)QOSP_CODEGEN_REV);
  if (!qa->abi[0]) {
    fprintf(stderr,
            "[qos] warning: %s carries no abi stamp (pre-stamp archive); "
            "shell expects %s -- rebuild to silence\n",
            qa->id, want);
    return 0;
  }
  if (strcmp(qa->abi, want) != 0) {
    fprintf(stderr,
            "[qos] REFUSED: %s was built for abi %s but this shell is %s "
            "-- rebuild the app (and any plugins) against this shell\n",
            qa->id, qa->abi, want);
    return -1;
  }
  return 0;
}

static int perm_gate(qa_t *qa, int auto_yes) {
  for (int i = 0; i < qa->nperms; i++) {
    qa_perm_t *p = &qa->perms[i];
    if (auto_yes) { p->granted = 1; continue; }
    fprintf(stderr, "%s \"%s\" requests %s %s (%s) -- allow? [y/n] ",
            qa->name[0] ? qa->name : qa->id, qa->id, p->mode, p->url,
            p->required ? "required" : "optional");
    int c = getchar(), d;
    while ((d = getchar()) != '\n' && d != EOF) {}
    p->granted = (c == 'y' || c == 'Y');
    if (!p->granted && p->required) {
      fprintf(stderr,
              "Cannot Run Application without all required compulsory "
              "Permissions\n");
      return -1;
    }
  }
  return 0;
}

static void bus_handler(int sig, siginfo_t *info, void *vctx) {
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

int main(int argc, char **argv) {
  int auto_yes = 0;
  const char *qa_path = 0;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--yes")) auto_yes = 1;
    else if (!strcmp(argv[i], "--trace")) g_trace = 1;
    else qa_path = argv[i];
  }
  if (getenv("QOSP_TRACE")) g_trace = 1;
  if (getenv("QOSP_YES")) auto_yes = 1;
  if (!qa_path) {
    fprintf(stderr, "usage: qosp [--yes] [--trace] <app.qa>\n");
    return 2;
  }

  /* catch bus errors inside the loaded app for diagnosis */
  struct sigaction sa = {0};
  sa.sa_sigaction = bus_handler;
  sigemptyset(&sa.sa_mask);
  sa.sa_flags = SA_SIGINFO;
  sigaction(SIGBUS, &sa, NULL);
  sigaction(SIGSEGV, &sa, NULL);

  /* ---- Stage 1: Initializer ---------------------------------------- */
  TRACE("stage 1 (initializer): mapping arena at %#lx (+%lu MiB)\n",
        QOS_ARENA_BASE, QOS_ARENA_SIZE >> 20);
	void *arena =
      mmap((void *)QOS_ARENA_BASE, QOS_ARENA_SIZE, PROT_READ | PROT_WRITE,
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
      execvp(argv[0], argv);
      qos_hostlog("qosp: cannot retry arena mapping: %s", strerror(errno));
    }
#endif
    qos_hostlog("qosp: cannot map the arena at %#lx (ASLR collision or RWX "
                "policy) -- the app image is linked at this address, so "
                "there is no fallback",
                QOS_ARENA_BASE);
    return 1;
  }
#ifdef __APPLE__
  unsetenv("QOSP_ARENA_REEXEC");
#endif
  const qos_hal_t *hal = qosp_hal_table();
  TRACE("stage 1: HAL table at %p (abi v%" PRIu64 ")\n", (const void *)hal,
        hal->version);

  /* ---- Stage 2: Loader --------------------------------------------- */
  TRACE("stage 2 (loader): the image into the slot; the rest of the "
        "arena is the app's (abi v12)\n");

  qa_t qa;
  qos_snd_set_assets(qa_path); /* music and other assets resolve beside the .qa */
  if (qa_load(qa_path, &qa)) return 1;
  load_sha_hex(qa.load, qa.load_len, g_shell_sha, sizeof g_shell_sha);
  TRACE("stage 2: %s (id=%s, loadMode=%s), image %" PRIu64 "B, %d perms\n",
        qa.name, qa.id, qa.load_mode, qa.img_len, qa.nperms);
  if (qa.load_mode[0] && strcmp(qa.load_mode, "process")) {
    qos_hostlog("qosp: loadMode \"%s\" is a name-dispatch archive; qosp "
                "runs loadMode = \"process\" images",
                qa.load_mode);
    return 1;
  }
  if (abi_gate(&qa)) return 1;
  if (perm_gate(&qa, auto_yes)) return 1;

  fpr_elf_load_t ld = fpr_qaimg_load(qa.load, qa.load_len, qa.img, qa.img_len,
                                     (void *)QOS_SLOT_BASE, QOS_SLOT_SIZE);
  if (!ld.ok) {
    qos_hostlog("qosp: image load failed: %s", ld.err);
    return 1;
  }
	uint64_t arena_base = ((uint64_t)ld.image_end + 15) & ~15ull;
  uint64_t arena_size = (QOS_ARENA_BASE + QOS_ARENA_SIZE) - arena_base;
  TRACE("stage 2: image [%#lx..%p), entry %p, the app's arena %#" PRIx64
        " (+%" PRIu64 " MiB)\n",
        QOS_SLOT_BASE, ld.image_end, ld.entry, arena_base, arena_size >> 20);

	/* Publish the code: the arena is a single rw anonymous mapping, but on
   * macOS arm64 a page can never be writable and executable at once, so
   * flip just the executable prefix of the image (the PF_X PT_LOADs, as
   * reported by elfload) to r-x and leave everything after it -- rodata
   * tail, data, bss, heap, and the buddy arena -- rw.  The linker script
   * places .text first and the RW segment on its own 64 KiB-aligned page,
   * so the 16 KiB host-page round-up never captures a writable byte.
   * This runs on EVERY host: a plain rw anonymous mapping is NOT
   * executable on modern Linux either (NX applies; "no W^X policy"
   * only means an rwx mmap is *allowed*, not that rw implies x) --
   * discovered when the Darwin-only version of this block left Linux
   * qosp jumping into a non-exec page.  The icache clear below is
   * needed on any arm64 host. */
  {
    uintptr_t pg = (uintptr_t)getpagesize();
    uintptr_t xend = ((uintptr_t)ld.exec_end + pg - 1) & ~(pg - 1);
    if (xend <= (uintptr_t)QOS_SLOT_BASE || ld.exec_end == 0) {
      qos_hostlog("qosp: image has no executable segment");
      return 1;
    }
    if ((uintptr_t)ld.rw_start < xend) {
      qos_hostlog("qosp: executable pages would capture writable image data "
                  "(exec_end=%p rounds to %#lx, first rw byte at %p, page=%lu) "
                  "-- relink with page-separated segments",
                  ld.exec_end, (unsigned long)xend, ld.rw_start,
                  (unsigned long)pg);
      return 1;
    }
  { /* protection precondition (docs/QA-FORMAT.md): the r-x round-up
     * must not capture a writable byte.  qaimg reports the boundary;
     * the protector checks it -- the linker script's ALIGN(0x10000)
     * is what makes this pass. */
    uintptr_t pgq = (uintptr_t)getpagesize();
    uintptr_t xq = ((uintptr_t)ld.exec_end + pgq - 1) & ~(pgq - 1);
    if (ld.exec_end && (uintptr_t)ld.rw_start < xq) {
      qos_hostlog("qosp: image not page-separated (exec_end=%p rw=%p)",
                  ld.exec_end, ld.rw_start);
      return 1;
    }
  }
      if (mprotect((void *)QOS_SLOT_BASE, xend - QOS_SLOT_BASE,
                 PROT_READ | PROT_EXEC)) {
      perror("qosp: mprotect(code, r-x)");
      return 1;
    }
    TRACE("stage 2: code [%#lx..%#lx) r-x, data+heap rw\n",
          (unsigned long)QOS_SLOT_BASE, (unsigned long)xend);
  }
  __builtin___clear_cache((char *)QOS_SLOT_BASE, (char *)ld.image_end);

  /* sized to the grants; it lives as long as the app reads its boot record */
  uint64_t caps_len = 0;
  char *caps = qa_caps_serialize(&qa, &caps_len);
  if (!caps) {
    qos_hostlog("qosp: out of memory serializing the granted permissions");
    return 1;
  }
  qosp_store_bind(qa.id);

  qos_boot_t boot = {
      .abi_version = QOS_ABI_VERSION,
      .hal = hal,
      .heap_base = 0, /* v12: the app carves its own first slab */
      .heap_size = 0,
      .grow = 0,      /* v12: retired -- the arena is the app's */
      .caps = (const unsigned char *)caps,
      .caps_len = caps_len,
      .syscall_fn = qosp_store_call,
      .tls_off = qosp_tls_off(),
      .arena_base = (void *)arena_base,
      .arena_size = arena_size,
  };
  qosp_hal_set_smp(resolve_nharts(), start_hart_cb);
  /* the guaranteed first /logs/host line: which host, which app, how
   * many harts -- pends here, replays into the ring at registration */
  qos_hostlog("qosp: hosting %s (%" PRIu64 " harts, abi v%u)",
              qa.name[0] ? qa.name : qa.id, resolve_nharts(),
              (unsigned)QOS_ABI_VERSION);
  TRACE("stage 2: nharts %" PRIu64 " (cores %ld), tls_off %" PRId64 "\n",
        resolve_nharts(), sysconf(_SC_NPROCESSORS_ONLN),
        (int64_t)boot.tls_off);

	/* ---- Stage 3: the app's own world -------------------------------- */
  TRACE("stage 3: entering the app\n");
  static char result[64 * 1024];
  qos_app_entry_t entry = (qos_app_entry_t)ld.entry;
  int64_t rc = entry(&boot, result, sizeof result);
  join_harts(); /* every hart loop exited through fpr_process_done */
  if (rc) {
    qos_hostlog("qosp: app entry rejected the boot record (%" PRId64
                ", abi mismatch?)",
                rc);
    return 1;
  }
  printf("\n[qos] %s => %s\n", qa.id, result);
  qa_free(&qa);
  return 0;
}