/* process.c -- System.qa's side of dynamic loading: the growth
 * callback handed to a running process, and the FPRISC-facing
 * Sys.placeImageAt primitive that ties buddy.c + qaimg.c + proc_entry
 * together (docs/2026-10-01-PROCESS-IMAGES.md).
 *
 * A process image is a block of memory like any other: Memory.qa's buddy
 * hands it out, the image is copied in and its address words are moved to
 * wherever the block is (it is linked at 0, with a RELOC list), and it is
 * registered as process pid's image.  There is no slot: as many processes
 * run at once as memory holds.  The block goes back to the buddy when the
 * last actor of its process has been reclaimed.
 */
#include "fpr.h"

/* set from system.fpr's boot path via a thin wrapper below; keeps
 * buddy_init out of the fully-shared fpr_rt_init (a plain machine boot
 * with no process loading has no reason to reserve/init this arena) */
void fpr_proc_arena_init(void) {
  /* slab refactor: buddy is init'd over heap+proc regions at boot
   * (fpr_rt_init) for EVERY image -- it is the machine's one lower
   * allocator now.  Sys.init stays in the boot protocol as a no-op so
   * existing system.fpr code keeps working unchanged. */
}

/* ---- the storage SYSCALL channel ------------------------------------
 * A loaded process lives in its own scheduler world: it cannot `send`
 * to System.qa's actors.  Instead System.qa passes ONE C function
 * through the entry ABI; the process-side svc helpers call it, and it
 * -- running System.qa's code -- publishes into the storage actor
 * (spawned on hart 1, so it makes progress while hart 0 is inside the
 * process) with the dormant syscall mailbox as replyTo, then spins for
 * the Result.  Capability scoping is enforced HERE, structurally: a
 * process may only name the relative url "kv", which the trampoline
 * rewrites to apps/<id>/<id>.kv from the id System.qa bound at launch.
 * Tags: 2 append, 3 replay (the kv event-sourcing pair). */
static V g_store_actor;   /* Sys.bindStore, at boot (0 = diskless) */
static str_t *g_app_id;   /* Sys.bindApp, per launch */

/* The RPC envelope is a DECLARED FPR constructor now (svc.fpr's Rpc),
 * and constructor tids are content-addressed by (unit hash, type name) —
 * C cannot know the tag statically. So bindStore takes a PROTOTYPE Rpc
 * value alongside the actor: we read tid/var off its header once at
 * boot and mint real Rpc values from then on. The tid crosses the ABI
 * as data, which is the only place it can honestly live. */
static uw g_rpc_tid; /* from the bind-time prototype */
static uw g_rpc_var;
static V g_sys_bind_store(V a, V rpc_proto) {
  g_store_actor = a;
  hdr_t *p = (hdr_t *)rpc_proto;
  g_rpc_tid = p->tid;
  g_rpc_var = p->var;
  return (V)&fpr_unit;
}
/* the id the NEXT placement is launched as (copied into its image record) */
static V g_sys_bind_app(V idv) {
  if (ISINT(idv) || ((hdr_t *)idv)->tid != T_STR) fpr_cpanic("Sys.bindApp: id must be a String");
  g_app_id = (str_t *)idv;
  return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2ebindStore, g_sys_bind_store, 2);
FPR_FN(fpr_g_Sys_x2ebindApp, g_sys_bind_app, 1);

/* mint an Rpc constructor value (4 fields) with the bind-time tag.
 * The old scheme here — a Tup2 header carrying 4 slots — was exactly
 * the silent-corruption ABI the compiler now rejects at compile time;
 * this was its last C-side survivor. */
/* the storage actor's mailbox is Dynamic; a refusal here means the
 * machine is out of memory, and a syscall cannot proceed without it */
static void send_or_die(uw key, V to, V msg) {
  for (int t = 0; t < 1000; t++) {
    if (fpr_sent(fpr_send_as(key, to, msg))) return;
    __asm__ volatile("" ::: "memory");
  }
  fpr_cpanic("syscall: the storage actor's mailbox refused the request");
}
static V mkrpc(V a, V b, V c, V d) {
  if (!g_rpc_tid) fpr_cpanic("store call before bindStore prototype");
  hdr_t *t = (hdr_t *)fpr_alloc(8 + 4 * sizeof(uw));
  t->tid = g_rpc_tid;
  t->var = g_rpc_var;
  V *f = (V *)((char *)t + 8);
  f[0] = a; f[1] = b; f[2] = c; f[3] = d;
  return (V)t;
}

/* ---- the shared plane (transparent process ACBs) --------------------
 * A process's actors run on the kernel's own scheduler under its pid.
 * Each loaded image carries its own record at the head of its block: the
 * registry entry, the boot record the image keeps for its whole life
 * (on_exit runs at its root's exit), and the app id it was launched as --
 * the kv capability is scoped by the CALLER's pid, so processes running at
 * once each reach only their own file. */
typedef struct {
  fpr_sched_t *sched;
  void *reply;
  uw pid;
  void (*on_exit)(void);
} shared_boot_t;
typedef struct {
  fpr_image_t im;     /* lo/hi: the whole buddy block; owner: this record */
  shared_boot_t sb;
  void *block;        /* what buddy_alloc returned */
  int ending;         /* taken by the one teardown */
  uw idlen;
  char id[];          /* the app id (Sys.bindApp) */
} proc_image_t;
static fpr_sched_t g_kernel_sched;
static int g_sched_ready;
static uw g_next_pid = 1;
static fpr_lock_t g_img_lock; /* serializes teardown against lookups by pid */
static void shared_on_exit(void) {} /* the root's exit; the image goes with the pid */

static proc_image_t *image_of_pid(uw pid) {
  fpr_image_t *im = fpr_image_of_pid(pid);
  return im ? (proc_image_t *)im->owner : 0;
}

/* fpr_pid_quiet (actors.c reap): an actor of pid was reclaimed.  When none
 * of that process's actors is left -- none can run its code -- the image
 * is unregistered and its block goes home. */
static void image_quiet(uw pid) {
  fpr_lock(&g_img_lock);
  proc_image_t *pi = image_of_pid(pid);
  if (!pi || pi->ending || fpr_pid_live(pid)) { fpr_unlock(&g_img_lock); return; }
  pi->ending = 1;
  fpr_image_remove(&pi->im);
  fpr_unlock(&g_img_lock);
  buddy_free(pi->block);
}

sw qos_store_call(uw tag, const char *pay, uw plen, char *out, uw outcap) {
  if (!g_store_actor) return -2; /* no disk */
  if (tag != 2 && tag != 3) return -3;
  /* apps/<id>/<id>.kv, where <id> is the CALLING process's own app id */
  fpr_lock(&g_img_lock);
  proc_image_t *pi = image_of_pid(fpr_current_pid());
  char url[128];
  uw n = 0;
  if (pi) {
    const char *pre = "apps/";
    for (const char *q = pre; *q; q++) url[n++] = *q;
    for (uw i = 0; i < pi->idlen && n < 100; i++) url[n++] = pi->id[i];
    url[n++] = '/';
    for (uw i = 0; i < pi->idlen && n < 120; i++) url[n++] = pi->id[i];
    const char *suf = ".kv";
    for (const char *q = suf; *q; q++) url[n++] = *q;
  }
  fpr_unlock(&g_img_lock);
  if (!pi) return -2; /* not a loaded process: no app bound */

  V urlv = (V)fpr_mkstr((const uint8_t *)url, n);
  V payv = (V)fpr_mkstr((const uint8_t *)pay, plen);
  /* the calling PROCESS ACB is the replyTo -- kv IO is an ordinary actor
   * round trip (a blocking receive frees the hart) */
  void *me = fpr_hart()->current;
  V msg = mkrpc((V)me, TAG((sw)tag), urlv, payv);
  send_or_die((uw)me, g_store_actor, msg);
  V r = fpr_receive_res_c((V)me);
  /* r = Ok s | Err s (builtin Result, variant 0/1), field at +8 */
  hdr_t *h = (hdr_t *)r;
  str_t *s = (str_t *)*(V *)((char *)h + 8);
  uw cp = s->len < outcap ? s->len : outcap;
  for (uw i = 0; i < cp; i++) out[i] = (char)s->bytes[i];
  return h->var == 0 ? (sw)cp : -1;
}


/* a growth grant is a shared-buddy slab: it is reaped with the acbs that
 * own it, so the loader keeps no ledger of its own (it once kept a
 * 64-entry one that nothing read) and a process may grow without count */
static fpr_grant_t loader_grow_memory(uw want_bytes) {
  fpr_grant_t g = {0, 0};
  void *p = buddy_alloc(want_bytes);
  if (p) {
    g.ptr = p;
    g.size = buddy_block_usable_size(p);
  }
  return g;
}

static V mktup2v(V a, V b) {
  hdr_t *t = (hdr_t *)fpr_alloc(8 + 2 * sizeof(uw));
  t->tid = T_TUP2;
  t->var = 0;
  *(V *)((char *)t + 8) = a;
  *(V *)((char *)t + 8 + sizeof(uw)) = b;
  return (V)t;
}

static V refuse(const char *why) {
  uw n = 0;
  while (why[n]) n++;
  return mktup2v(TAG(0), (V)fpr_mkstr((const uint8_t *)why, n));
}

/* Sys.placeImageAt : String -> List Int -> List Int -> String -> (Int, String)
 * The ARCHIVE bytes; the extents [IMAGE offset, IMAGE length, RELOC offset,
 * RELOC length] of its sections; LOAD's numbers [base, entry, execsz, rwoff,
 * memsz] as programs/mods/qaimg.fpr read them; and the capability blob.  The
 * payloads are read straight out of the .qa String's own bytes, never as
 * pre-sliced copies.  fst = 2 "running under this pid" / 0 failure; snd =
 * the pid, or a human-readable reason.  Argument-type errors panic, like
 * every HAL primitive; anything about the image or memory is reported
 * through the tuple, so the launcher keeps running and says what went
 * wrong. */
static V g_sys_place_image_at(V qastr, V extv, V numsv, V capsv) {
  if (ISINT(capsv) || ((hdr_t *)capsv)->tid != T_STR)
    fpr_cpanic("Sys.placeImageAt: caps must be a String (the serialized grant blob)");
  if (ISINT(qastr) || ((hdr_t *)qastr)->tid != T_STR)
    fpr_cpanic("Sys.placeImageAt: first argument must be a String (the .qa archive bytes)");
  uw ext[4], nums[5];
  if (!fpr_list_ints(extv, ext, 4))
    fpr_cpanic("Sys.placeImageAt: extents must be [image offset, image length, reloc offset, reloc length]");
  if (!fpr_list_ints(numsv, nums, 5))
    fpr_cpanic("Sys.placeImageAt: nums must be [base, entry, execsz, rwoff, memsz]");
  str_t *qa = (str_t *)qastr;
  uw ioff = ext[0], ilen = ext[1], roff = ext[2], rlen = ext[3];
  if (ioff > qa->len || ilen > qa->len - ioff)
    fpr_cpanic("Sys.placeImageAt: the IMAGE extent is out of range for this archive");
  if (roff > qa->len || rlen > qa->len - roff)
    fpr_cpanic("Sys.placeImageAt: the RELOC extent is out of range for this archive");
  if (nums[0] != 0)
    return refuse("not a relocatable image (linked for a fixed slot): rebuild it with tools/build-process-app.sh");
  uw memsz = nums[4];

  /* the block: the record, then the image at the next 4 KiB boundary */
  uw idlen = g_app_id ? g_app_id->len : 0;
  uw head = (sizeof(proc_image_t) + idlen + 15) & ~(uw)15;
  void *blk = buddy_alloc(head + 4096 + memsz);
  if (!blk) return refuse("no memory for the image");
  proc_image_t *pi = (proc_image_t *)blk;
  unsigned char *img = (unsigned char *)(((uw)blk + head + 4095) & ~(uw)4095);
  fpr_qaimg_t q = {(uw)img, nums[1], nums[2], nums[3], memsz};
  fpr_elf_load_t r = fpr_qaimg_place(&q, qa->bytes + ioff, ilen, img, memsz);
  const char *bad = r.ok ? fpr_qaimg_relocate(img, ilen, qa->bytes + roff, rlen) : r.err;
  if (bad) {
    buddy_free(blk);
    return refuse(bad);
  }
  /* new instructions in memory the I-cache may remember as something else */
  fpr_code_publish(); /* local fence now; remote fences before dispatch */

  if (!g_sched_ready) {
    fpr_sched_export(&g_kernel_sched);
    g_sched_ready = 1;
  }
  uw pid = __atomic_fetch_add(&g_next_pid, 1, __ATOMIC_RELAXED);
  pi->im.lo = (char *)blk - sizeof(uw); /* the block's own header */
  pi->im.hi = (char *)blk + buddy_block_usable_size(blk);
  pi->im.pid = pid;
  pi->im.owner = pi;
  pi->block = blk;
  pi->ending = 0;
  pi->idlen = idlen;
  for (uw i = 0; i < idlen; i++) pi->id[i] = (char)g_app_id->bytes[i];
  pi->sb.sched = &g_kernel_sched;
  pi->sb.reply = fpr_hart()->current; /* the launcher actor gets the result */
  pi->sb.pid = pid;
  pi->sb.on_exit = shared_on_exit;
  if (!fpr_pid_quiet) fpr_pid_quiet = image_quiet;
  /* registered BEFORE the root is spawned: from here its cells are statics
   * to the kernel, and what leaves the process is decided against its pid */
  fpr_image_add(&pi->im);

  /* the process's OWN fpr_process_entry: it spawns the root actor under
   * pid and returns.  heap_base/heap_size/grow belong to the retired
   * nested-scheduler path and are unused on the shared plane. */
  str_t *cs = (str_t *)capsv;
  V (*entry)(void *, uw, fpr_grant_t (*)(uw), const unsigned char *, uw,
             sw (*)(uw, const char *, uw, char *, uw), void *) =
      (V (*)(void *, uw, fpr_grant_t (*)(uw), const unsigned char *, uw,
             sw (*)(uw, const char *, uw, char *, uw), void *))r.entry;
  entry(r.image_end, 0, loader_grow_memory, cs->bytes, cs->len, qos_store_call, &pi->sb);
  /* a process that started nothing, or has already ended, goes now */
  image_quiet(pid);

  char pm[32];
  uw pn = 0;
  const char *pp = "pid ";
  for (const char *c = pp; *c; c++) pm[pn++] = *c;
  {
    uw v = pid, st = pn;
    do { pm[pn++] = (char)('0' + v % 10); v /= 10; } while (v);
    for (uw i = 0; i < (pn - st) / 2; i++) {
      char t = pm[st + i]; pm[st + i] = pm[pn - 1 - i]; pm[pn - 1 - i] = t;
    }
  }
  return mktup2v(TAG(2), (V)fpr_mkstr((const uint8_t *)pm, pn));
}

FPR_FN(fpr_g_Sys_x2eplaceImageAt, g_sys_place_image_at, 4);

/* Sys.init : Unit -> Unit -- must be called once, before the first
 * Sys.loadElf, by whichever image owns the process arena (System.qa's
 * boot path). Not folded into fpr_rt_init: plenty of images link
 * runtime.c without ever linking buddy.c/process.c (every demo that
 * isn't System.qa), so this stays an opt-in call, not a hook everyone
 * pays for. */
static V g_sys_init(V d) { (void)d; fpr_proc_arena_init(); return (V)&fpr_unit; }
FPR_FN(fpr_g_Sys_x2einit, g_sys_init, 1);

/* Sys.images : Int -> Int -- process images loaded now (each goes when its
 * process has ended) */
static V g_sys_images(V d) { (void)d; return TAG((sw)fpr_image_count()); }
FPR_FN(fpr_g_Sys_x2eimages, g_sys_images, 1);

/* introspection: how much of the buddy (the heap) is currently free */
static V g_sys_arena_free(V d) { (void)d; return TAG((sw)buddy_free_bytes()); }
FPR_FN(fpr_g_Sys_x2earenaFree, g_sys_arena_free, 1);
