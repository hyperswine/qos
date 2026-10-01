# The native launcher leaked while idle

Date: 2026-10-01. Kind: bug record.

The native launcher (`programs/system.fpr`, `lWait`/`lTick`) waited for a
key by spinning: `svcPollKey`, then `svcClock`, then repeat, with no pause.
Every poll goes through `Svc.read`. Its route allocates a substring
(`segAfter`) and boxes the reply (`IInt`), and the launcher actor's pool is
only reclaimed when the actor dies. An idle launcher therefore grew without
bound. Left at the menu for 40 s, the kernel panicked with
`heap exhausted (no block for a slab)` after 125 MiB, both with and without
the compiler's new inliner.

The `QAR2 process load` and `Transparent ACBs` check-all legs launch at about
6 s. They passed only while the compiled code was slow enough not to reach
the limit by then. FP-RISC's base-profile inliner (fprisc
`docs/2026-09-30-NATIVE-PERF.md`, 2026-10-01 section) made the poll loop
faster and the legs failed. A bisect over which functions were inlined
looked layout-dependent, because the real dependency was on time.

**Fix.** `lWait` now runs the wait (`lPoll`: a key, or 0 when the clock
second changes) inside `Sys.arena`. The garbage of every poll goes when the
arena returns, and only the key code leaves. `lPoll` also parks 1 ms between
empty polls, so an idle launcher no longer burns a hart. Verified: idle for
60 s, then launch, and the process runs.

**Still open.** Each redraw (once per second, and on every key) builds a new
frame buffer in the launcher's pool, which is still never reset. That is a
slow leak, about one 80x24 buffer per second. Bounding it needs a boundary
per frame (state sent to self, pool reset, received back) whose callers
provably hold nothing in the pool, or the launcher as its own actor that
restarts per session.
