# Storage reliability before further Main development

The candidate adds correlated storage deadlines, missing-only fallbacks and
finite service-owned resource budgets. The physical Pi campaign is recorded
under `.qos/pi4/validation/storage-reliability-20261013/`.

## Contracts

`Svc.TimedRpc caller id until tag key bytes` carries an absolute monotonic
microsecond deadline. The same deadline covers Files admission, queued time,
Qlog recovery and every routed page operation. Namespace Files calls carry it
through `Ep.Timed`. Defaults are ten seconds; `FS.rpcWithin`, `FS.rpcUntil`,
`FS.shutdownWithin`, and the block `submitUntil`/`awaitUntil` pair allow an
explicit budget. Legacy `submit` and `await` each use their own default budget;
retain one deadline explicitly when submission and joining must share a budget.

An expired queued page operation is refused before I/O. An admitted mutation
whose reply is lost or times out has an **unknown outcome**. It is never
replayed automatically. A later Files request can rescan committed state using
the same stable gateway address. Failed recovery latches the gateway offline.
Late correlated replies are ignored by idle gateway/endpoint receive loops.

Quiesce, drain and final flush share one storage shutdown deadline. Network stop
and storage shutdown share the lifecycle owner's finish budget. Logical drain
does not claim that an orphaned device operation released its buffers. A failed
barrier is an error; native unsupported durable flush remains explicit.

Only exact `no such file` permits a built-in/default value. Offline I/O and
corruption do not. Bootstrap archive lookup, app index and keypad mapping
preserve this distinction. Permission read, parse and persistence failures
refuse a launch. A file cached before an uncertain write is invalidated and
re-read before it can be served again. Loader replay reports storage errors;
only an absent `sys/live` is an empty replay.

## Service resource limits

| Resource | Bound and refusal |
| --- | --- |
| Storage key | 1,024 bytes |
| Storage request payload | 4 MiB |
| Pending block I/O | 64 requests globally, each write at most 4 KiB; at most 256 KiB of retained queued payload, plus active work and metadata |
| Block helper generations | 16 pairs per owner lifetime; successful I/O reuses helpers; exhaustion latches explicit refusal |
| Files Qlog generations | 3 total: initial startup plus at most two recoveries |
| Files endpoint leases | 64 total; 60-second expiry; dead clients swept on the next request; reads, writes and closes retain client ownership |
| Dynamically created Qsys file actors | 64 per file manager |
| Main validation reload images | 2 generations, attached once; subsequent cycles reuse scoped bindings |

Storage actors now opt into `Sys.spawnInbox` limits across all producers,
including messages still being copied:

| Inbox | Global slots | Charged bytes |
| --- | ---: | ---: |
| Block owner | 64 | 8 MiB |
| Each block helper | 2 | 256 KiB |
| Files owner, direct Qlog, endpoint, namespace adapter and Qsys file/manager | 8 | 16 MiB |
| Recoverable Qlog child | 2 | 16 MiB |

Reservation precedes copying. Oversized graphs fail immediately; exhaustion
returns `mailbox full`. Dequeue, refused publication and sender/receiver death
release charges. Selective receives move per-slot charges with the values.
Charge arrays are allocated only for opted-in actors and reclaimed through a
separate reuse pool; legacy channel blocks avoid the inline accounting array.
ARC sharing and linear moves retain their ownership behavior, including refusals
and loaded-process routing. The graph walk has a depth ceiling and stops at the
budget, avoiding exponentially expanded copies.

Charged bytes conservatively include copied representation, message slab floor
and allocation rounding. This is an inbox bound, not a cap on allocator arenas,
application-held values or all transitive ARC retention. Other actors keep their
existing mailbox behavior. Plain spawn still has no universal process creation
quota. The core inbox change was explicitly approved after the initial broader
runtime proposal was rejected by automatic approval review.

## Wire migration

Published identities include actor v3, ep v3, svc v5, blockio v6, Qlog v10,
Files client v5, endpoint owner v3, net v3 and lifecycle v6. The module lock
records exact immutable versions. Rebuild the shell, services and onboard
archives together: old nominal endpoint/storage constructors are incompatible.
Existing immutable blobs are preserved.

The native storage syscall uses the same correlation namespace and selective
nonblocking receive with a ten-second deadline. `bindStore` rejects the old
four-field prototype. FP-RISC exports selective
nonblocking receive and appends inbox admission plus ARC/linear send callbacks
to actor plane ABI 3. Native ABI remains 6 and memory plane ABI remains 2.
Loaded-process `Sys.sleepUs` now uses the existing plane sleep callback; it
previously fell through to the process image's weak no-op fallback. Hosted
shutdown acknowledgement now hands control to the scheduler unconditionally;
a one-microsecond sleep could return before parking and resume into a panic.

## Reproducible validation

- `python3 tools/storage-reliability-check.py`: live hangs, stale replies,
  queued/namespace deadline propagation, no replay, recovery exhaustion,
  endpoint ownership/limits, finite helpers and refusal retention; one/four workers.
- `python3 tools/storage-fallback-check.py`: actual RV64 bootstrap helpers,
  offline archives and permission read/write/parse failures.
- `../fprisc/tests/check_inbox.py`: global producer/byte limits, bounded graph
  expansion, selective receive, ownership, deterministic kill windows and
  admission rollback; one/four workers.
- `python3 tools/native-inbox-check.py`: actual RV64 process-plane ARC/linear
  ownership, sleep delegation and image reclamation; virtio v1/v2, one/two harts.
- Existing block service/lifecycle, Files shutdown, Qlog routing, durable
  storage, native failure injection, Main GL, publication/reload and smoke
  checks cover adjacent behavior. Their fresh results are recorded below.
- `tools/pi4/build-main-reliability.py`: isolated ARM64 SDK candidate, matching
  onboard plugins, hidden reload fixtures, manifests and file hashes.
- `tools/pi4/main-soak.py --harts 1|4 --seconds 1200 --memory-probe
  --reliability-probe`: real EGL/V3D Main, Files/Logs/Browser switching,
  scoped old/new plugin functions, live hung-peer timeout, real SD progress
  records, allocator/RSS samples, normal quit and a second signal shutdown.

The Pi uses a separate SD-backed disk and leaves the installed service running.
The reload probe loads exactly two generations because detached plugin images
remain mapped in this loader. Repeated checks verify scoped functions and state
without manufacturing unbounded image retention. The injected hung peer is also
reused. Allocator reservations and ARC root counts are diagnostics, not proof of
object reachability. Simulated storage failures do not establish physical
power-loss durability.

## Results

Validation is still running. Final evidence and exact Pi metrics will be added
after both physical soak legs finish.
