# Live-service deadlines and task joins

Date: 2026-10-13. QOS pins FP-RISC `6ad33f0` for this change. This follows the block-worker reuse and service-failure work.

FP-RISC adds selective nonblocking receives, absolute-budget correlated calls,
a reusable legacy session that retires after failure, default/configurable MVU
service deadlines, and owned task joins that detect worker death and cancel
siblings. Full contracts and limitations are in
[FP-RISC's implementation record](../../fprisc/docs/2026-10-13-DEADLINES-JOINS.md).

Main now applies its five-second service budget to startup dimensions, MVU
input/port/render turns and graphics close. A live dependency or render worker
that stalls returns a failure through Main's existing storage shutdown path.
Graphics close is attempted with its own budget; its failure is attached to
the primary failure. Storage shutdown retains its existing coordinated barrier.
Synchronous boot/update/reload calls and the storage stack's upper service
waits are separate boundaries; this is not a universal OS deadline retrofit.

The campaign also exposed and fixed a scheduler lock deadlock during dead
actor reclamation, a per-hart string-formatting race across allocation, and
loaded native processes using the disabled local allocator for scratch loops.
Actor-plane and memory-plane ABIs advance to 2 (native runtime ABI remains 6).
Native processes and the plane must be rebuilt together. Integrity tests check
explicit rejection of both legacy ABI 1 tables before placement.

## Executed evidence

- Complete FP-RISC Base suite passes. QOS smoke passes 16/16; the module
  lock validates all 56 source pins. Native launcher smoke reaches the
  launcher at +0.26 seconds. Targeted standard-library call/task
  application fixtures also match their existing outputs.

- FP-RISC deadline/join fixtures: one/four workers, including stale/late replies,
  unrelated inbox messages, FIFO overflow, live service stalls, watcher cleanup,
  worker death, sibling/owner cancellation, ordered/concurrency-limited batches
  and finite failed-join memory retention after warm-up. Named par2 failure and
  Sol selective receive/deadline parity also pass.
- Sixty consecutive four-worker host watched-timeout campaigns pass after the
  original hang reproduced. A deterministic C test checks that dead actor
  cleanup can re-enter scheduler admission after the backlog lock is released.
- QOS loaded native process tests exercise selective polls, live deadlines,
  healthy/failed joins and scratch arenas through the plane on one/two RV64
  harts. Native integrity/placement tests run on virtio v1/v2, one/two harts.
- Real desktop GL Main: normal two-boot UI campaign and graphics-death cleanup
  pass. A separate deliberately stalled render callback stays live past a
  one-second test budget: Main drains/flushes storage before reporting the
  deadline failure, clears readiness and exits with status 1.

The physical Pi 4 campaign uses SDK-linked standalone diagnostics with a
64 MiB application arena. Actor deadlines, task failure handling and MVU live
service deadlines pass with one and four workers. Ten additional consecutive
four-worker MVU deadline campaigns pass after repairing the scheduler deadlock.
The installed QOS process remains PID 31331; no installed host, application or
storage disk was replaced. Hardware evidence and executable hashes are retained
under the ignored `.qos/pi4/validation/deadlines-20261013/` directory. Initial
failure evidence is preserved there as well. Host GL evidence is retained under
`/tmp/qos-deadline-shell/`.

These checks are finite regression evidence. Permanent actor identities,
plain-spawn resource failure, restart admission, arbitrary Base panics and
synchronous foreign work remain outside this change. An admitted timed-out
operation has unknown outcome; neither MVU nor task cancellation proves that
external side effects stopped.
