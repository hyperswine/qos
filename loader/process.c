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
 * -- running System.qa's code -- sends to the storage actor with the
 * calling process ACB as replyTo and PARKS that actor for the reply
 * (receiveFromRes: a refused send or a dead storage actor is an error
 * to the process, never a wait).  Capability scoping is enforced HERE, structurally: a
 * process may only name the relative url "kv", which the trampoline
 * rewrites to apps/<id>/<id>.kv from the id System.qa bound at launch.
 * Tags: 2 append, 3 replay (the kv event-sourcing pair). */
static V g_store_actor;   /* Sys.bindStore, at boot (0 = diskless) */
static str_t *g_app_id;   /* Sys.bindApp, per launch */
static V g_ns;            /* Sys.bindNs, at boot: the namespace a process reaches with Sys.ns */

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
/* Sys.bindNs ns: the namespace actor (mods/ep.fpr) every loaded process is
 * handed in its boot record -- its Sys.ns -- so it opens urls like any
 * actor on the plane, judged by the grants the launcher recorded under
 * its pid */
static V g_sys_bind_ns(V a) { g_ns = a; return (V)&fpr_unit; }
FPR_FN(fpr_g_Sys_x2ebindNs, g_sys_bind_ns, 1);

/* mint an Rpc constructor value (4 fields) with the bind-time tag.
 * The old scheme here — a Tup2 header carrying 4 slots — was exactly
 * the silent-corruption ABI the compiler now rejects at compile time;
 * this was its last C-side survivor. */
/* a request that could not be made: the reason goes to the process in
 * out (NUL-terminated when it fits) with -1, as a storage Err does */
static sw store_refused(const char *why, char *out, uw outcap) {
  uw k = 0;
  while (why[k] && k < outcap) { out[k] = why[k]; k++; }
  if (k < outcap) out[k] = 0;
  return -1;
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
  void *root;         /* set by the process entry: its root actor (the launcher's correlation) */
  void *ns;           /* the namespace actor, or 0 (Sys.ns in the process) */
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
/* Sys.reservePid: the launcher takes the pid BEFORE placement, so the
 * namespace can hold the process's grants before its first instruction */
static V g_sys_reserve_pid(V d) { (void)d; return TAG((sw)__atomic_fetch_add(&g_next_pid, 1, __ATOMIC_RELAXED)); }
FPR_FN(fpr_g_Sys_x2ereservePid, g_sys_reserve_pid, 1);
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
  /* the storage actor's mailbox is Dynamic; a refusal is the machine out
   * of memory, or the actor gone -- the PROCESS hears it, the kernel runs on */
  if (!fpr_sent(fpr_send_as((uw)me, g_store_actor, msg)))
    return store_refused("storage: the storage actor refused the request", out, outcap);
  /* the reply is the storage actor's own: Ok <its Result>, or Err "dead
   * actor" when it ended first (receiveFromRes wraps the message) */
  V w = fpr_receive_from_res_c((V)me, g_store_actor);
  V r = ((hdr_t *)w)->var == 0 ? *(V *)((char *)w + 8) : w;
  /* r = Ok s | Err s (builtin Result, variant 0/1), field at +8 */
  hdr_t *h = (hdr_t *)r;
  str_t *s = (str_t *)*(V *)((char *)h + 8);
  uw cp = s->len < outcap ? s->len : outcap;
  for (uw i = 0; i < cp; i++) out[i] = (char)s->bytes[i];
  if (cp < outcap) out[cp] = 0;
  return h->var == 0 ? (sw)cp : -1;
}

#ifdef QOS_PROCESS_TEST
/* Static mailboxes are bounded PER SENDER. A test kernel fills the
 * process root's channel before letting that process call the real ABI. */
static V g_sys_test_fill_from(V target, V sender, V count) {
  sw n = UNTAG(count);
  for (sw i = 0; i < n; i++)
    if (!fpr_sent(fpr_send_as((uw)sender, target, TAG(i))))
      fpr_cpanic("process test: channel refused before its capacity");
  return fpr_send_as((uw)sender, target, TAG(n));
}
FPR_FN(fpr_g_Sys_x2etestFillFrom, g_sys_test_fill_from, 3);
#endif


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

static V mktup3v(V a, V b, V c) {
  hdr_t *t = (hdr_t *)fpr_alloc(8 + 3 * sizeof(uw));
  t->tid = T_TUP3;
  t->var = 0;
  *(V *)((char *)t + 8) = a;
  *(V *)((char *)t + 8 + sizeof(uw)) = b;
  *(V *)((char *)t + 8 + 2 * sizeof(uw)) = c;
  return (V)t;
}

static V refuse(const char *why) {
  uw n = 0;
  while (why[n]) n++;
  return mktup3v(TAG(0), (V)fpr_mkstr((const uint8_t *)why, n), TAG(0));
}

void qosp_sha256_pair(const unsigned char *, uint64_t, const unsigned char *, uint64_t, unsigned char[32]);

static int digest_is(V wantv, const unsigned char *a, uw an, const unsigned char *b, uw bn) {
  if (ISINT(wantv) || TID(wantv) != T_STR) fpr_cpanic("native image digest must be a String");
  str_t *want = (str_t *)wantv;
  if (want->len != 64) return 0;
  unsigned char digest[32];
  qosp_sha256_pair(a, an, b, bn, digest);
  static const char hex[] = "0123456789abcdef";
  for (uw i = 0; i < 32; i++)
    if (want->bytes[2*i] != hex[digest[i] >> 4] || want->bytes[2*i+1] != hex[digest[i] & 15]) return 0;
  return 1;
}

/* Shared by launcher preflight and placement itself. No image backing,
 * publication or execution can happen until this gate succeeds. Hashes are
 * integrity claims supplied from LOAD, not signatures or authorization. */
static const char *check_image(V qastr, V extv, V numsv, V shav, V relshav, uw ext[6], uw nums[6]) {
  if (ISINT(qastr) || TID(qastr) != T_STR) fpr_cpanic("native image archive must be a String");
  if (!fpr_list_ints(extv, ext, 6))
    return "native image extents must cover IMAGE, RELOC and IMPORT";
  if (!fpr_list_ints(numsv, nums, 6))
    return "native runtime ABI missing: rebuild the process with tools/build-process-app.sh";
  if (nums[5] != FPR_NATIVE_ABI)
    return "native runtime ABI mismatch: rebuild the process with tools/build-process-app.sh";
  str_t *qa = (str_t *)qastr;
  for (uw i = 0; i < 6; i += 2)
    if (ext[i] > qa->len || ext[i+1] > qa->len - ext[i]) return "native image section outside archive";
  if (nums[0] != 0)
    return "not a relocatable image (linked for a fixed slot): rebuild it with tools/build-process-app.sh";
  if (!nums[4] || ext[1] > nums[4] || nums[2] > ext[1] || nums[1] >= nums[2] || nums[3] > nums[4])
    return "native image LOAD spans inconsistent";
  if (!digest_is(shav, qa->bytes + ext[0], ext[1], 0, 0))
    return "IMAGE sha256 mismatch (corrupt archive or missing digest)";
  if (!digest_is(relshav, qa->bytes + ext[2], ext[3], qa->bytes + ext[4], ext[5]))
    return "RELOC sha256 mismatch (corrupt archive or missing digest)";
  if (ext[5]) return "native process IMPORT is unsupported: rebuild a self-contained process";
  return 0;
}

/* Preflight before the launcher reserves a pid or records permission grants.
 * Placement repeats the gate so direct callers cannot skip integrity checks. */
static V g_sys_check_image(V qa, V extv, V numsv, V sha, V relsha) {
  uw ext[6], nums[6];
  const char *bad = check_image(qa, extv, numsv, sha, relsha, ext, nums);
  if (bad) return fpr_mkresult(1, bad);
  hdr_t *ok = (hdr_t *)fpr_alloc(8 + sizeof(V));
  ok->tid = T_RESULT; ok->var = 0;
  *(V *)((char *)ok + 8) = (V)&fpr_unit;
  return (V)ok;
}
FPR_FN(fpr_g_Sys_x2echeckImage, g_sys_check_image, 5);

#ifdef QOS_PROCESS_TEST
static uw test_image_allocs;
static V g_test_image_allocs(V unit) { (void)unit; return TAG(test_image_allocs); }
FPR_FN(fpr_g_Sys_x2etestImageAllocs, g_test_image_allocs, 1);
#endif

/* Sys.placeImageAt qa [IMAGE off,len, RELOC off,len, IMPORT off,len]
 * [base,entry,execsz,rwoff,memsz,nativeabi] caps pid (sha,relsha)
 * -> (2, pid description, root actor), or (0, refusal, 0).
 * Digest failures return before any image buddy request or publication. */
static V g_sys_place_image_at(V qastr, V extv, V numsv, V capsv, V pidv, V digests) {
  if (ISINT(digests) || TID(digests) != T_TUP2) fpr_cpanic("Sys.placeImageAt: digests must be a pair");
  V shav = *(V *)((char *)digests + 8), relshav = *(V *)((char *)digests + 8 + sizeof(V));
  if (ISINT(capsv) || TID(capsv) != T_STR) fpr_cpanic("Sys.placeImageAt: caps must be a String");
  if (!ISINT(pidv) || UNTAG(pidv) < 0) fpr_cpanic("Sys.placeImageAt: pid must be an Int");
  uw ext[6], nums[6];
  const char *invalid = check_image(qastr, extv, numsv, shav, relshav, ext, nums);
  if (invalid) return refuse(invalid);
  str_t *qa = (str_t *)qastr;
  uw ioff = ext[0], ilen = ext[1], roff = ext[2], rlen = ext[3];
  uw memsz = nums[4];
  uw idlen = g_app_id ? g_app_id->len : 0;
  if (idlen > ~(uw)0 - sizeof(proc_image_t) - 15)
    return refuse("native image identifier size out of range");
  uw head = (sizeof(proc_image_t) + idlen + 15) & ~(uw)15;
  if (head > ~(uw)0 - 4096 || memsz > ~(uw)0 - head - 4096)
    return refuse("native image memory size out of range");
#ifdef QOS_PROCESS_TEST
  test_image_allocs++;
#endif

  /* the block: the record, then the image at the next 4 KiB boundary */
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
  uw pid = UNTAG(pidv) ? (uw)UNTAG(pidv) : __atomic_fetch_add(&g_next_pid, 1, __ATOMIC_RELAXED);
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
  pi->sb.root = 0;
  pi->sb.ns = (void *)g_ns;
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
  /* the root actor, read before the record can go: a process that started
   * nothing, or has already ended, is freed by the next line */
  V root = pi->sb.root ? (V)pi->sb.root : TAG(0);
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
  return mktup3v(TAG(2), (V)fpr_mkstr((const uint8_t *)pm, pn), root);
}

FPR_FN(fpr_g_Sys_x2eplaceImageAt, g_sys_place_image_at, 6);

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
