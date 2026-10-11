# Automatic receive-turn coverage and Pi regression

Date: 2026-10-12. FP-RISC `27870ae`, pinned by QOS together with the coverage
gate and soak driver described here. Validation used the corresponding source
changes on top of QOS `b9821c6`. The installed Pi supervisor/session is separate
from this validation.

## Static inventory

`python3 tools/receive-coverage.py --out /tmp/receive-coverage.json` compiles
Main and all four onboard apps, saves compiler logs and JSON, and separates
automatic groups, explicit region owners and skipped groups. Whole-program
and unit-local reports are deduplicated. `--entry` restricts the inventory.
Add `--check` to enforce `tools/receive-coverage-expectations.json`: a required
group may be automatic or explicitly managed, but may not disappear or become
skipped. All five entries pass this check; the earlier compiler inventory
correctly fails 14 required boundary checks.

These are receive-reaching recursive call groups in the compiled dependency
closure, including exported helpers that may never run in Main. They are not
actor counts, dynamic coverage, or a proof that all live data is bounded.

| Entry | Automatic before | Automatic after | Explicit regions after | Skipped after |
|---|---:|---:|---:|---:|
| Main | 2 | 9 | 40 | 6 |
| Clock plugin | 1 | 3 | 1 | 6 |
| Logs plugin | 1 | 3 | 1 | 6 |
| Browser plugin | 1 | 3 | 1 | 6 |
| Disk plugin | 1 | 3 | 1 | 6 |

Main's newly automatic groups are interrupt routing, endpoint-open reply
redirection, MVU text rendering, MVU input draining, app registration and the
legacy file actor. Existing logging admission and graphics mesh traversal
remain automatic. Existing explicit regions in namespace, Files/Qlog, block,
network, graphics and MVU frame/event owners remain in control.
The follow-up typed-event collector adds the ninth group: `eventPortsAcc`
tail-accumulates event batches while preserving subscription order, per-port
FIFO and duplicate suppression, including already-seen ports.

## Compiler and ownership changes

- A turn starts at a source receive entry. Source helpers between entries
  and compiler-generated clause/case joins run inside the current turn;
  temporary request payloads and callbacks do not become copied loop state.
  Generated joins retain shared code and are identified by compiler provenance.
- Entry state contains only live parameters. A least fixed point handles
  parameters forwarded around mutual recursion but never inspected. Argument
  effects still run strictly, left to right; public helper behavior is preserved.
- Zero-argument entries use delayed Unit state. Named record shapes can supply
  closed value evidence inside nominal declarations.
- Non-returning proof covers every SCC member, including joins. A returning
  callback/unknown result cannot acquire value ownership from a join's lack
  of interface metadata. Live mutable/function state and unproved results
  remain skipped; runtime Vector graph checks remain active.
- MVU Ev/Sub and QOS app metadata have concrete protocol fields. Generic
  renderer payloads remain supported, including scalar renderers in the real
  reload test. Message schema changes require rebuilding dependent images.
- The text renderer and legacy file actor explicitly keep the received graph
  and drop its ARC root before handing it to helpers. Automatic reclamation
  alone does not discharge the received-root ownership law.

The native runtime ABI remains 6 and code generation revision remains 39.
The changed compiler pass has a separate assembly-cache tag, `rt3pc1`.
No runtime allocator or reference-counting implementation changed here.

## Remaining groups and next work

| Main's skipped groups | Reason / next step |
|---|---|
| Two published `AC.awaitReply` versions | Generic result ownership. Carry checked specialization evidence into the pass before permitting generic results. |
| Published legacy namespace | Existential fields in `NsSt`; migrate clients to the bounded endpoint implementation or publish a concrete, versioned protocol. |
| Published legacy directory listing | A receive-capable helper takes a generic `Ep` request; published compatibility prevents silently changing that declaration. |
| Published generic endpoint server | Long-lived reader/writer callbacks need capture ownership evidence. |
| Prelude generic `serve` | Callback and model ownership remain unknown. |

Growing queues, models and registries still need admission policies. Fixed
heap grants still refuse scratch regions that lack separate admission. Precise
Base ARC and general higher-order/non-tail recursion remain separate work.

## Executed verification

- macOS ARM64: automatic receive tests on one/four workers, including zero
  arguments, shared joins, shadowed captures, strict effects, dead forwarding,
  temporary callbacks and linear vectors, cache opt-out and cancellation.
- MVU text renderer: 20,000 requests on one/four workers with a 64 MiB heap;
  logical retained memory below 4 MiB and stable received-root counts.
- Linux ARM64: the same complete automatic-receive driver passed.
- RV64: the extended coverage fixture linked freestanding and executed on
  four-hart QEMU, including temporary Vector ownership.
- Symbolic cost checks and paired primitive/automatic runtime ledgers passed.
  State copying remains additional work; quick runs are not throughput evidence.
- Case-fallback native/Sol semantics and linear Core/bytecode growth checks passed.
- QOS Portable MVU and real one/four-worker plugin reloads passed, including
  scalar rendering, retained state, old closures and incompatible-update refusals.

The complete Base regression suite exited successfully, including child-only
resource failures, fixed heaps, actor teardown, IRQ routing, ARC ownership,
Vector kernels and live module replacement. QOS Native also linked and booted
to its launcher under QEMU at +0.34 s.

## Physical Pi runtime checks

Physical Raspberry Pi 4 Model B Rev 1.4, aarch64 Buildroot Linux, Wi-Fi.
The SDK-linked host, Main app and all onboard plugins were rebuilt together.
All 874 compared Haskell/FPR/C/header/assembly source files matched the isolated
Linux build checkout. Bundle SHA-256:
`f81b1b1d46158659c264b830e3808c46cd039d26f5d3fb85eaece902a0b95f1c`.
The source manifest and executable hashes are retained with the ignored
validation artifacts.

Each fixture ran with a 64 MiB heap, without timeout or forced termination:

| Fixture | Workers | Duration | Peak RSS |
|---|---:|---:|---:|
| One million ordinary receives | 1 | 8.06 s | 1,920 KiB |
| One million ordinary receives | 4 | 8.22 s | 1,920 KiB |
| Extended zero-arg/join/dead-state/temporary-ownership coverage | 1 | 0.76 s | 2,048 KiB |
| Same extended coverage | 4 | 0.76 s | 1,920 KiB |
| 20,000 text-renderer requests and released roots | 1 | 0.35 s | 2,432 KiB |
| Same renderer check | 4 | 0.45 s | 2,304 KiB |

Observed CPU frequency was 600 MHz; peak sampled temperature was 60.9 C.
These fixture assertions measure logical allocations and roots separately
from the runner's resident-memory readings.

## Main workload

The mixed Main workload completed 23 acknowledged Files/Logs/Browser cycles
on four workers, with a separate SD-backed disk, `FPR_HEAP_MB=256`,
and the real surfaceless V3D EGL/GLES backend. Both boots exited successfully,
without timeout or forced kill; both readiness files were removed.
The subsequent allocator probe established that this environment setting
caps the hosted Base runtime, not the loaded QOS application's buddy arena.
That arena used the host's default address-space reservation, not a 256 MiB
cap. The driver now sets `QOSP_ARENA_MB` explicitly (default 256 MiB).

| Run | Duration | Result |
|---|---:|---|
| Mixed UI/scroll/navigation, then normal quit | 914.74 s | Storage drained and flushed; 23 successful workload cycles |
| Same SD disk, second boot, SIGTERM | 30.09 s | Host acknowledged graceful shutdown |

Across 23 samples, RSS rose from 43,344 to 45,480 KiB (+2,136 KiB); PSS rose
from 37,819 to 39,955 KiB. The runner's peak RSS was 49,536 KiB. Peak runner
sampled temperature was 63.3 C, at an observed 600 MHz CPU frequency. Global
V3D BO totals rose from 50 objects / 14,636 KiB to 54 / 16,060 KiB; these include
the installed session and cannot be assigned solely to this test.

The run passed its 16 MiB sampled-RSS growth guard, but memory was not flat.
Smaps attributes 1,808 KiB of the 2,136 KiB increase to existing anonymous
mappings within the QOS arena address range; the host libc heap grew by 16 KiB.
This does not distinguish logically retained data from newly resident pages
in a reusable allocator. A multi-hour mixed workload with runtime logical
pool/root counters alongside RSS and per-process graphics attribution remains
necessary before claiming steady-state Main memory.

The test PID stayed stable. The installed service remained
`running pid=31331 restarts=0` throughout, and its app/disk were not replaced.
The successfully drained SD test disk was removed; logs and memory samples
remain available.

`tools/pi4/main-soak.py` is reusable with a longer `--seconds` value. Its RSS
growth threshold is a regression guard, not a proof of bounded memory. GPU BO
figures are global, not per-process allocation counts. No display-output or
power-loss durability claim follows from this test.

Raw evidence is under `.qos/pi4/validation/receive-coverage-20261012/`.

## Typed-port follow-up and allocator attribution

`tests/base/mvueventports.fpr` covers all typed event variants, multiple ports,
subscription/FIFO order, empty ports, initial exclusions and duplicates. A
counting responder verifies that duplicate subscriptions do not issue extra
drains. On one/four workers it checks 20,000 three-port batches, stable ARC
roots and less than 4 MiB retained buddy allocation. macOS ARM64 and physical
Pi runs passed; four-hart RV64 QEMU also passed. Physical Pi runtimes were
7.93 s / 21.63 s, with peak RSS 4,224 / 4,864 KiB at 600 MHz. These are test
observations, not a throughput comparison with the old collector.

`tests/mainmemory.fpr` shares the real Main boot, shell, plugins and shutdown,
using `Shell.runWith` to wrap only the update callback. The test-only F12 probe
samples the allocator between workload cycles. The regular Main update
callback and key behavior are preserved. `main-soak.py --memory-probe` requires
this entry, validates each sample and stores it with Linux residency.

The initial diagnostic run (default QOS arena reservation, before correcting
the driver cap) completed eight Files/Logs/Browser cycles in 316.01 s. RSS
rose from 43,060 to 44,656 KiB (+1,596 KiB), while buddy reservations rose from
27,328 to 27,584 KiB (+256 KiB). ARC roots stayed at 19, and the model actor's
cumulative pool bump gauge stayed at 3,949,824 bytes. Normal quit drained the
store; a second boot stopped by SIGTERM completed in 30.08 s. Both exited 0
without timeout/forced kill, and the installed session stayed unchanged.

These observations distinguish allocator block reservations from page
residency; they do not prove object reachability or rule out slower growth.
The kernel supplied no per-process DRM fdinfo counters, so graphics
attribution is still limited to the global V3D totals. A longer capped soak
and more precise graphics attribution remain necessary.

Evidence is under `.qos/pi4/validation/eventports-20261012/`; the matching
Mac/ARM64 VM semantic-source comparison checked 876 files with no differences.

With the corrected driver and `--arena-mib 64`, the same candidate completed
eight cycles in 314.31 s, followed by a successful 30.08 s SIGTERM boot. Its
buddy arena measured 63,104 KiB after image placement/alignment, confirming
the real application limit. RSS rose 42,604 -> 44,096 KiB (+1,492 KiB);
buddy reservations rose 26,368 -> 26,624 KiB (+256 KiB). All eight samples
reported 19 ARC roots and 3,949,824 model-owner bump bytes. Reservations were
flat after warm-up; RSS changed by only 12 KiB across the final four samples.
Peak runner RSS was 48,208 KiB. Both boots exited 0 without forced termination,
both readiness files were removed, the successfully drained test disk was
removed, and the installed supervisor remained `running pid=31331 restarts=0`.
This five-minute capped run validates the harness and short-term behavior;
it does not replace the pending longer soak. Evidence is under
`.qos/pi4/validation/eventports-capped-20261012/`.

The complete macOS Base suite, real MVU reload checks, QOS MVU smoke, shell
input/scroll regressions and QOS native link/boot also passed after the
follow-up. Runtime ABI 6/code generation revision 39 remain unchanged.
