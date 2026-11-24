/* timed_receive.c -- deadline receives for QOS on the pinned FP-RISC runtime.
 *
 * std/actor's deadline calls wait by polling receiveFromNow and napping
 * 100 us between looks (154 us per call where a blocking receive answers in
 * under 1 us: docs/2026-11-24-TIMED-RECEIVE.md).  FP-RISC main grows builtin
 * deadline receives (receiveUntil/receiveFromUntil, hyperswine/fprisc#112);
 * until QOS's fprisc pin moves there, these are the same waits as QOS
 * primitives (core/foreign.fpr), built on what the pinned runtime already
 * exports: fpr_wait_{any,from}_until_c park the actor on its mailbox AND its
 * hart's sleeper list through the runtime's block/recheck handshake, so a
 * send from any hart or the deadline wakes it, whichever comes first.
 *
 *   Sys.receiveUntil me until          : Result a String
 *       Ok message (any sender) | Err "deadline"
 *   Sys.receiveFromUntil me from until : Result a String
 *       Ok message from `from` (others stay queued) | Err "deadline" |
 *       the dead-sender Err of receiveFromNow once `from` ended, drained
 *   Sys.waitInbox me until             : Int
 *       park until ANY message is queued or the deadline passes, taking
 *       nothing: 1 ready without parking, 2 woken after parking, 0 no
 *       timed wait here (a plane process): the caller paces itself
 *
 * `until` is a std/actor deadline: absolute milliseconds on Sys.uptimeMs
 * (10 MHz timebase).  The mailbox is looked at first: a queued message is
 * taken even past the deadline, and an expired deadline is one poll, never
 * a park.  A wake that finds nothing re-checks the clock and parks for the
 * time left.  Timeouts answer one static Err: they allocate nothing.
 *
 * Included by hal/core/lifecycle.c (native kernel, native processes,
 * Spectre) and qos/appside/hal.c (Portable app images), so every image that
 * links QOS's lifecycle primitives links these too. */
#include "fpr.h"

static const struct { uint32_t tid, var; uw len; uint8_t bytes[16]; } __attribute__((aligned(8))) qtr_deadline_s = {T_STR, 0, 8, "deadline"};
static const struct { uint32_t tid, var; V f; } __attribute__((aligned(8))) qtr_deadline = {T_RESULT, 1, (V)&qtr_deadline_s};

/* receiveNow's direct entry (actors.c FPR_FN): Ok message | Err "empty" */
V fpr_g_receiveNow_call1(V me);

static uint64_t qtr_ticks(V until) {
  if (!ISINT(until)) fpr_cpanic("timed receive: deadline must be an Int (ms)");
  sw ms = UNTAG(until);
  if (ms <= 0) return 0;
  if ((uint64_t)ms > UINT64_MAX / 10000) return UINT64_MAX;
  return (uint64_t)ms * 10000;
}

static int qtr_empty(V result) {
  str_t *why = (str_t *)FPR_FLD(result, 0);
  return why->len == 5 && why->bytes[0] == 'e' && why->bytes[1] == 'm' &&
         why->bytes[2] == 'p' && why->bytes[3] == 't' && why->bytes[4] == 'y';
}

/* One park until a message (from `from`, or any when 0) or the deadline.
 * The pinned runtime answers 0 in two cases: an earlier Sys.sleepUs entry
 * still linked on another hart's sleeper list (the actor migrated mid-sleep)
 * -- a 1 us parked sleep cancels it, after which the wait parks -- and a
 * process on the kernel's plane (plane ABI v6 has no deadline receive).
 * There it naps until the fprisc pin moves to plane ABI v7, keeping the
 * pacing each caller had before: `slice_us` is 100 for a reply wait
 * (std/actor's napUntil) and the whole time left for receiveUntil (whose
 * callers slept their full period, 16-25 ms, then looked), at most 1 s. */
static void qtr_park(V me, V from, uint64_t deadline, uint64_t slice_us) {
  int waited = from ? fpr_wait_from_until_c(me, from, deadline) : fpr_wait_any_until_c(me, deadline);
  if (waited) return;
  if (!fpr_plane_actors) { fpr_actor_sleep_us(1); return; }
  uint64_t now = hal_mtime();
  uint64_t left = deadline > now ? (deadline - now) / 10 : 0;
  if (left > slice_us) left = slice_us;
  fpr_actor_sleep_us((uw)(left ? left : 1));
}

static V qtr_receive_until(V me, V until) {
  uint64_t deadline = qtr_ticks(until);
  for (;;) {
    V r = fpr_g_receiveNow_call1(me);
    if (((hdr_t *)r)->var == 0) return r;
    if (hal_mtime() >= deadline) return (V)&qtr_deadline;
    qtr_park(me, 0, deadline, 1000000);
  }
}

static V qtr_receive_from_until(V me, V from, V until) {
  if (ISINT(from) || !from) fpr_cpanic("Sys.receiveFromUntil: sender is not an actor");
  uint64_t deadline = qtr_ticks(until);
  for (;;) {
    V r = fpr_receive_from_now_c(me, from);
    if (((hdr_t *)r)->var == 0 || !qtr_empty(r)) return r; /* a message, or the sender ended */
    if (hal_mtime() >= deadline) return (V)&qtr_deadline;
    qtr_park(me, from, deadline, 100);
  }
}

static V qtr_wait_inbox(V me, V until) {
  return TAG(fpr_wait_any_until_c(me, qtr_ticks(until)));
}

FPR_FN(fpr_g_Sys_x2ereceiveUntil, qtr_receive_until, 2);
FPR_FN(fpr_g_Sys_x2ereceiveFromUntil, qtr_receive_from_until, 3);
FPR_FN(fpr_g_Sys_x2ewaitInbox, qtr_wait_inbox, 2);
