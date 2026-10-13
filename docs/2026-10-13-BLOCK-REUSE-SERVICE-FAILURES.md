# Reusable block workers and service-call failure handling

Date: 2026-10-13. Scope: QOS Portable and RV64 Native block adapter;
FP-RISC MVU service admission/death handling and Main cleanup. QOS pins
FP-RISC `4c6ff7f1408121ba1ceb79b296c03b1aa7091ea8`.

## Block ownership

`std/blockio.fpr` now retains one worker and one completion relay between
successful requests. Only the owner sends work. The worker answers the relay
with the request token; the relay watches that worker, then reports the token
and outcome to the owner. The owner accepts only its active relay/token pair.
Both helpers reclaim request scratch between turns and observe owner death
while idle. No actor address or identity is recycled.

Active cancellation still kills the worker and reports outcome unknown.
The owner waits for its relay's completion before advancing the queue; a
subsequent request replaces a dead worker. Queued cancellation still proves
that I/O did not start. Admission, the queue bound, closed drain state and the
administrator's final flush retain their existing behavior. A cancelled or
failed worker necessarily leaves a permanent actor identity; repeated failures
and growing application state still require separate admission/restart policy.

The module store and source pins are updated through Block, BlockEP, Qlog,
Files and Lifecycle to the system/Main compositions. The stored protocol type
identities change, so dependent archives must be rebuilt together. The exact
previous Files interface is listed in `core/trusted-modules.txt`, following
its existing prior-interface convention; no blanket store trust was added.

## Service calls

FP-RISC `std/mvu` adds `svcCallRes`, Result-returning port helpers, `runResult`,
`runLiveResult` and `runWithResult`. Existing value-returning facades retain
their successful behavior and issue a named error on service failure.

The existing renderer/input `(caller, request)` wire is retained. Admission
refusal and service death are Results. The internal frame-worker wire uses
correlated requests/replies. Dimensions, input, ordinary/typed event-port and
render failures exit the driver, stop its owned worker and return an error.
The watched runner also stops its watcher and port on these Result exits.
Reference text-render and event-port replies retry mailbox pressure instead
of silently losing an admitted caller's reply. `std/actor.askSureRes` provides
the same explicit death path for legacy asks; `askSure` reports a named error.

Main uses the Result runner. Its input adapter ends normally on graphics
service failure so the driver receives a death Result rather than a process
panic. Main stops its input and event-port actors, closes its
graphics handle and invokes coordinated storage shutdown before reporting an
error. Startup dimensions/attachment failure also reaches shutdown. Cleanup
errors are attached to the primary error rather than discarded. Main logs
the combined failure and explicitly completes shutdown with status 1, so
the host clears readiness and reports failure after the storage barrier.

This does not add deadlines to a live service that never replies, change the
machine-wide Base panic contract, catch arbitrary callback panics, or fix the
separate `Task.collect`/`receiveRes` death-notification gap. The legacy external
wire remains uncorrelated; migration to a common correlated service envelope
is separate work. Indefinite reply retries remain a backpressure policy,
not an end-to-end deadline.

## Verification

- `tools/block-lifecycle-check.py`: Portable one/two workers and RV64 QEMU
  one/two harts with virtio v1/v2. Cancellation, queue bounds, forged completion,
  drain, namespace routing and the new 8,192-read memory regression pass.
- The same memory fixture against the previously stored block adapter fails:
  8,192 reads retain 11,712 KiB. The new fixture requires under 2 MiB overall
  and under 1 MiB in the second batch after warm-up.
- `tools/block-service-check.py`: all four Native budget/refusal/recovery cases
  pass, including worker fail-stop, caller death and terminal device refusal.
- `tools/qlog-memory-check.py`: one/four-worker, two-boot binary read/replay,
  mutation, tombstone and compaction checks pass under an explicit 64 MiB
  application arena. Forty large reads retain 0 KiB; the complete workload
  retains 448 KiB in each local case. The prior report recorded about 25 MiB.
  The fixture now asserts a 4 MiB global-growth guard in addition to its
  Qlog-local allocation limit. This is finite-workload evidence.
- FP-RISC MVU reload, 20,000-frame and port memory tests pass on one/four
  workers. The new failure fixture checks already-dead services, death during
  dimensions/render/input, dead ports, render-worker death, full-mailbox
  admission, owned-watcher cleanup and a subsequent healthy run.
- Real QOS plugin reloads and checked-interface refusals pass on one/four
  workers. The real desktop GL Main harness passes two boots, Files/Logs
  scrolling, onboard Clock/Browser, refused archives and graceful shutdown.
- Receive coverage expectations name the Result-returning input/event
  collectors, whose automatic value-state boundaries remain present.

The standard-library suite's poller golden output expects zero caller
allocation around 100,000 empty receives, but observes 112 bytes. An isolated
copy of the unchanged HEAD libraries reproduces the same mismatch. This
baseline issue is not repaired here; other std legs are checked separately.

## Physical Pi 4

The SDK-linked diagnostic host and fixtures ran on the enrolled Raspberry Pi
4 Model B, Buildroot/Linux AArch64, at the existing governor. The application
arena was explicitly capped at 64 MiB. One/four-worker runs passed:

| Fixture | One worker | Four workers |
|---|---:|---:|
| MVU service/worker/port failure and subsequent healthy run | 0.041 s | 0.041 s |
| Legacy/correlated actor calls, admission and peer death | 0.062 s | 0.061 s |
| 8,192 reads after warm-up, bounded global retention | 3.917 s | 8.363 s |
| Active/queued cancellation and closed drain | 0.961 s | 0.979 s |

The separate SD-backed Qlog campaign passed two boots each on one and four
workers, checking binary reads, replay, mutations, tombstones and compaction.
Every case retained 448 KiB globally and under 4 MiB in Qlog's sampled pool.
Its successful test disks were removed after the two-boot checks.

Evidence and executable hashes are retained under the ignored directories
`.qos/pi4/validation/block-reuse-20261013/` and
`.qos/pi4/validation/block-reuse-qlog-20261013/`. These are targeted fixture
runs, not throughput comparisons or an extended Main soak. The installed
service remained application PID 31331 before/after the fixture campaign.
No installed Pi host, application or disk was replaced.

The ARM64 build VM was started for this validation. Candidate sources and
SDK outputs are isolated under `~/qos-block-reuse-candidate/`; its existing
source checkouts were preserved. The desktop GL harness and raw local
regression outputs are retained under `/tmp/qos-reuse-service-shell-net/`,
`/tmp/qos-block-reuse-qlog-capped/` and the corresponding `/tmp` driver logs.

## Final regression status

QOS smoke passes 16/16; the final input-adapter death regression also passes.
The final real-GL graphics-death fixture separately confirms storage drain,
combined primary/graphics-close errors, explicit failed completion (exit 1)
and readiness removal. Its log is
`/tmp/qos-reuse-shell-failure-final/failure-final.log`. The two normal GL boots
and this corrected failure leg were executed separately; an initial failure
leg exposed the missing failed-completion/readiness cleanup and was retained.
The complete FP-RISC Base regression exits successfully, including automatic
receive coverage, ownership/admission, MVU/reload, process images and native
code-generation checks. The std suite's other legs pass with the independently
reproduced baseline poller mismatch explicitly skipped; the unmodified full
std driver still fails that golden comparison. This is not a full std pass.

Portable durable-storage checks also pass all corrupt-media, migration,
append/reopen, staged-compaction and injected-flush boundaries. Portable
shutdown checks pass signals, normal return, refused/stuck acknowledgements,
flush-error exit 1, stalled-flush exit 124 and full output pipes. No physical
power-cut test or multi-hour Main soak is claimed.

The build VM was shut down after candidate compilation, restoring its initial
stopped state. Local commits preserve this source pairing; they are not pushed
and the Pi's installed application is not upgraded.
