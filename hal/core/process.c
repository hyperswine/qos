/* process.c -- System.qa's side of dynamic loading: the growth
 * callback handed to a running process, and the FPRISC-facing
 * Sys.loadImageAt primitive that ties buddy.c + qaimg.c + proc_entry
 * together. docs/PROCESS-LOADING.md has the full design; this file is
 * the last mile that makes it callable from FPRISC.  (The ELF loader it
 * first used, elfload.c, was retired by qaimg's flat image and is gone.)
 *
 * ONE arena, buddy_init'd once from fpr_rt_init's caller (see the hook
 * below); ONE concurrent process slot this pass (stated in the docs).
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

/* the callback wired into fpr_process_entry (runtime.c's fpr_alloc
 * calls it through fpr_grow_memory on bump exhaustion). Captures no
 * state -- single concurrent slot means "ask the one arena" is
 * unambiguous; a multi-slot future version would close over which
 * process is asking. */
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
 * One process at a time (the single slot); its root actor's exit
 * clears the gate through on_exit so the next launch may reuse the
 * slot.  Actors a process leaves running past its root are its own
 * bug -- the slot must not be reloaded under them. */
typedef struct {
  fpr_sched_t *sched;
  void *reply;
  uw pid;
  void (*on_exit)(void);
} shared_boot_t;
static fpr_sched_t g_kernel_sched;
static int g_sched_ready;
static uw g_next_pid = 1;
static volatile int g_shared_live;
static void shared_on_exit(void) { g_shared_live = 0; }

sw qos_store_call(uw tag, const char *pay, uw plen, char *out, uw outcap) {
  if (!g_store_actor || !g_app_id) return -2; /* no disk / no app bound */
  if (tag != 2 && tag != 3) return -3;
  /* apps/<id>/<id>.kv */
  char url[128];
  uw n = 0;
  const char *pre = "apps/";
  for (const char *q = pre; *q; q++) url[n++] = *q;
  for (uw i = 0; i < g_app_id->len && n < 100; i++) url[n++] = (char)g_app_id->bytes[i];
  url[n++] = '/';
  for (uw i = 0; i < g_app_id->len && n < 120; i++) url[n++] = (char)g_app_id->bytes[i];
  const char *suf = ".kv";
  for (const char *q = suf; *q; q++) url[n++] = *q;

  V urlv = (V)fpr_mkstr((const uint8_t *)url, n);
  V payv = (V)fpr_mkstr((const uint8_t *)pay, plen);
  V r;
  if (g_shared_live) {
    /* shared plane: the calling PROCESS ACB is the replyTo -- kv IO
     * becomes an ordinary actor round trip (blocking receive frees
     * the hart; no mailbox spin, no hart-1 assumption) */
    void *me = fpr_hart()->current;
    V msg = mkrpc((V)me, TAG((sw)tag), urlv, payv);
    send_or_die((uw)me, g_store_actor, msg);
    r = fpr_receive_res_c((V)me);
  } else {
    V mb = (V)fpr_syscall_mailbox();
    V msg = mkrpc(mb, TAG((sw)tag), urlv, payv);
    send_or_die((uw)mb, g_store_actor, msg);
    r = fpr_syscall_wait_result();
  }
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

/* Sys.loadImageAt : String -> Int -> Int -> Int -> Int -> caps -> (Int, String)
 * The ARCHIVE bytes plus the (offset, length) of its LOAD and of its IMAGE
 * section: the payload is read straight out of the .qa String's own bytes,
 * never as a pre-sliced copy.  fst = 1 success / 0 failure / 2 "queued under
 * this pid"; snd = the rendered result, the pid, or a human-readable reason.
 * Argument-type errors panic, like every HAL primitive; a malformed PAYLOAD
 * is reported through the tuple, so the launcher keeps running and says what
 * went wrong, the way "No such app" and "Bad .qa" do in system.fpr. */
/* QAR2: the launcher hands over the LOAD and IMAGE section extents of
 * the archive string -- never materialized as separate FPRISC Strings
 * (the O(n^2)-slice hazard PROCESS-LOADING.md records applies to the
 * multi-KB image payload exactly as it did to the ELF one). */
static V g_sys_load_image_at(V qastr, V loffv, V llenv, V ioffv, V ilenv, V capsv) {
  if (ISINT(capsv) || ((hdr_t *)capsv)->tid != T_STR)
    fpr_cpanic("Sys.loadImageAt: caps must be a String (the serialized grant blob)");
  if (ISINT(qastr) || ((hdr_t *)qastr)->tid != T_STR)
    fpr_cpanic("Sys.loadImageAt: first argument must be a String (the .qa archive bytes)");
  if (!ISINT(loffv) || !ISINT(llenv) || !ISINT(ioffv) || !ISINT(ilenv))
    fpr_cpanic("Sys.loadImageAt: section extents must be Ints");
  str_t *qa = (str_t *)qastr;
  sw loff = UNTAG(loffv), llen = UNTAG(llenv);
  sw ioff = UNTAG(ioffv), ilen = UNTAG(ilenv);
  if (loff < 0 || llen < 0 || (uw)loff + (uw)llen > qa->len ||
      ioff < 0 || ilen < 0 || (uw)ioff + (uw)ilen > qa->len)
    fpr_cpanic("Sys.loadImageAt: section extents out of range for this archive");
  const unsigned char *lbytes = qa->bytes + loff;
  const unsigned char *ibytes = qa->bytes + ioff;
  uw blen = (uw)ilen;

  /* the image is LINKED at _proc_arena_start: the fixed region IS the
   * slot (one concurrent process, per the docs) -- no allocation, no
   * fragmentation interplay with the slab heap.  Growth grants still
   * come from buddy and are reclaimed on exit. */
  void *slot = _proc_arena_start;
  uw slot_size = (uw)(_proc_arena_end - _proc_arena_start);
  if (blen + (64 * 1024) > slot_size)
    return mktup2v(TAG(0), (V)fpr_mkstr((const uint8_t *)"image larger than the process slot", 34));

  fpr_static_lo = fpr_static_hi = 0; /* the outgoing image's window, if any */
  fpr_elf_load_t r = fpr_qaimg_load(lbytes, (uw)llen, ibytes, blen, slot, slot_size);
  if (!r.ok) {
    uw n = 0; while (r.err[n]) n++;
    return mktup2v(TAG(0), (V)fpr_mkstr((const uint8_t *)r.err, n));
  }

  void *heap_base = r.image_end;
  uw heap_size = (uw)slot + slot_size - (uw)heap_base;
  /* the loaded image's cells are STATICS inside the buddy span: no
   * alloc preheaders, so the deep-copier (spawn's entry pap, any
   * static a process actor sends) and ARC must skip them (fpr.h) */
  fpr_static_lo = (char *)slot;
  fpr_static_hi = (char *)r.image_end;

  /* the process's OWN fpr_process_entry returns its result directly --
   * see the note in proc_entry.c about why this must not be fetched
   * via a same-named function call from THIS (System.qa's) image. */
  if (g_shared_live)
    return mktup2v(TAG(0), (V)fpr_mkstr(
        (const uint8_t *)"a process is still running in the slot", 39));
  str_t *cs = (str_t *)capsv;
  V (*entry)(void *, uw, fpr_grant_t (*)(uw), const unsigned char *, uw,
             sw (*)(uw, const char *, uw, char *, uw), void *) =
      (V (*)(void *, uw, fpr_grant_t (*)(uw), const unsigned char *, uw,
             sw (*)(uw, const char *, uw, char *, uw), void *))r.entry;
  if (!g_sched_ready) {
    fpr_sched_export(&g_kernel_sched);
    g_sched_ready = 1;
  }
  static shared_boot_t sb; /* single slot: one launch at a time */
  sb.sched = &g_kernel_sched;
  sb.reply = fpr_hart()->current; /* the launcher actor gets the result */
  sb.pid = g_next_pid++;
  sb.on_exit = shared_on_exit;
  g_shared_live = 1;
  entry(heap_base, heap_size, loader_grow_memory, cs->bytes, cs->len,
        qos_store_call, &sb);
  /* the root ACB is queued with our pid; ok=2 tells the launcher to
   * receiveRes for main's result.  Growth grants are shared-buddy
   * slabs reaped with the acbs, so nothing to free here. */
  char pm[32];
  uw pn = 0;
  const char *pp = "pid ";
  for (const char *q = pp; *q; q++) pm[pn++] = *q;
  {
    uw v = sb.pid, st = pn;
    do { pm[pn++] = (char)('0' + v % 10); v /= 10; } while (v);
    for (uw i = 0; i < (pn - st) / 2; i++) {
      char t = pm[st + i]; pm[st + i] = pm[pn - 1 - i]; pm[pn - 1 - i] = t;
    }
  }
  return mktup2v(TAG(2), (V)fpr_mkstr((const uint8_t *)pm, pn));
}

FPR_FN(fpr_g_Sys_x2eloadImageAt, g_sys_load_image_at, 6);

/* Sys.init : Unit -> Unit -- must be called once, before the first
 * Sys.loadElf, by whichever image owns the process arena (System.qa's
 * boot path). Not folded into fpr_rt_init: plenty of images link
 * runtime.c without ever linking buddy.c/process.c (every demo that
 * isn't System.qa), so this stays an opt-in call, not a hook everyone
 * pays for. */
static V g_sys_init(V d) { (void)d; fpr_proc_arena_init(); return (V)&fpr_unit; }
FPR_FN(fpr_g_Sys_x2einit, g_sys_init, 1);

/* introspection: how much of the process arena is currently free */
static V g_sys_arena_free(V d) { (void)d; return TAG((sw)buddy_free_bytes()); }
FPR_FN(fpr_g_Sys_x2earenaFree, g_sys_arena_free, 1);
