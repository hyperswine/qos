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

The implementation is checkpointed in QOS `60da4b4` and uses FP-RISC
`bfbdd8d`. The runtime commits were pushed through FP-RISC merge `0f4f6c2`,
which preserves concurrent view/deployment commits. QOS retains the tested
`bfbdd8d` toolchain pin; the merged runtime/compiler/actor contents are identical.
The final Pi bundle's 572 implementation files were checked against
the QOS checkpoint with no mismatches; documentation and concurrent STAR64
files were excluded. Exact source and artifact manifests are retained under
`.qos/pi4/validation/inbox-release-20261013/`.

Fresh checks passed: the full FP-RISC Base suite, including twelve 10-hart
Task.map stress runs per inliner setting and the original unread-mail memory
threshold; QOS smoke 16/16; inbox ownership, cancellation and six
admission rollback phases; RV64 loaded-process ownership/sleep/reclamation;
storage reliability on one/four workers; malformed permission/offline fallback
checks; native image integrity and actor ABI refusal; durable crash snapshots;
block queue/cancellation/drain and 8,192-read retention; Files shutdown with
orphan DMA accounting; Qlog stable-owner recovery and two System boots; native
read/mutation deadlines and malformed reply handling; real Main GL controls,
graphics death and live render deadline cleanup. The native stress test allows
60 seconds for its whole 8,192-read campaign after measured runs took 28-30
seconds; per-request budgets remain unchanged.

All 16 final physical Pi inbox/storage cases passed on one/four workers. The
installed service remained `running pid=31331 restarts=0`. Both final Main soaks passed, with normal quit and a separate SIGTERM boot
exiting cleanly in each leg. Each workload cycle switched Files/Logs/Browser,
checked both reload generations plus the old scoped function, bounded a live
hung peer, and appended an SD-backed progress record.

| Workers | Cycles | Sampling duration | RSS first / last / sampled peak (MiB) | Process high-water RSS (MiB) | ARC roots | Reserved first / last (MiB) |
| --- | ---: | ---: | --- | ---: | --- | --- |
| 1 | 42 | 1214.5 s | 41.9 / 44.5 / 44.9 | 48.8 | 11-11 | 29.4 / 31.4 |
| 4 | 41 | 1201.4 s | 42.5 / 44.7 / 45.6 | 49.7 | 11-11 | 29.4 / 31.3 |

Allocator reservations and root counts remain diagnostics rather than
reachability proof. The Pi reported 600 MHz during both legs; peak temperatures
were 59.9 C and 60.9 C. These are reliability results, not a frame-latency or
full-speed performance benchmark. Physical power-loss durability remains
untested. The installed service stayed at PID 31331 with zero restarts; only
the isolated successful test disks were removed. Aggregate results and raw
logs are retained in `inbox-release-20261013/complete.json` and its sibling
folders under the validation directory above.

Final candidate SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| `qosp-es` | `35cad357c96216fca3a9c7dec266deab99e120d216cd4db5b7c082f9a93d0d62` |
| `main.qa` | `04966a3d23b6f6f3245d36014ed2aff0e1dce34b49c0d1d76ba92ad5b642e9b9` |
| `Main.disk` | `18e0ae2de7def7add54c0eb1370ebea2d5593b586fa91b63dcb029ca2593663c` |
