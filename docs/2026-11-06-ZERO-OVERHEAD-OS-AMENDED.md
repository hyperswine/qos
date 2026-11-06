# Toward a zero-overhead QOS, amended: measured costs and a revised order

Date: 2026-11-06. Kind: amended proposal with measurements. No runtime change
is implemented by this page. It adds two benchmark programs.

Baseline: QOS `f2c3a63`, sibling FP-RISC checkout `aee02d8` (codegen 204).
`fprisc.lock.json` still names `1a09f01`, so these are not the release pin's
results. Host: arm64 macOS on Apple silicon, QOS Portable (`qosp`).

This page amends [the zero-overhead OS assessment](2026-11-06-ZERO-OVERHEAD-OS.md)
written earlier today. That page ranked twelve moves from source inspection.
This one measures the message path on QOS Portable, checks the cost table
against the code, and re-ranks. Review updates expand the contracts and gates
in both documents. The original now holds the detailed deferred designs,
including corrected transaction, scheduler and verification contracts; this
page owns the current joint order. All timings below remain historical
measurements, not results of this documentation revision.

## Summary

**What the measurements say** (`tests/ipcbench.fpr`, `tests/epbench.fpr`; raw
output in [evidence](evidence/2026-11-06-ipc-costs.txt)):

- A cross-hart round trip on QOS Portable costs **4,380 ns**, against 347 ns on
  the hosted FP-RISC runtime. With a two-line hook added to the app-side HAL
  as an experiment, it costs **446 ns**.
- A same-hart round trip costs 292 ns on Portable and 180 ns hosted. The 110 ns
  difference is not explained yet.
- A write that opens and closes its endpoint each time, as `Svc.write` does,
  costs **2,251 ns**. The same write on a held handle costs 553 ns.
- Copying is cheap for small messages and dominant for large ones: 1 KiB adds
  about 20 ns to a hosted round trip (on Portable it is inside run-to-run
  noise), while moving instead of copying a 16 KiB relay saves about 520 ns per three-hop cycle on Portable.
- An inbox bound costs about 15 ns per send when uncontended.

**What changes from the original:**

1. Move 1 keeps its rank and changes mechanism. The gain comes from the
   actor-level block spin, which QOS does not provide, and not from a spin in
   `park.c`.
2. Move 2 as written would not remove the copies it targets. It merges with
   Move 7 into one later item.
3. Move 5's proof machinery is deferred. Its uncontended cost is small;
   sender credits remain an experiment with refusal/fairness questions.
4. Move 9 rises: an empty native-storage poll incurs a sleep of up to 100 µs,
   not an unconditional per-operation floor.
5. Held handles are about 4.1x faster in this endpoint benchmark. That supports
   adopting existing handles at hot sites before designing a descriptor table.
   The call-site count is corrected from about 700 to 58.

**Revised order:** repeatable evidence, block spin, blocking C receive, hot-site
held handles and fixed-call profiling, then endpoint storage and large-message
transfer. Register fuel is a coordinated FP-RISC/QOS change; chunking and other
policy/proof projects remain deferred. See "Joint order of work" below.

## Measurements

### One message

Nanoseconds per round trip (a request and its reply), clock read around each
loop. `ipcbench.fpr` imports nothing, so the same file runs on both runtimes.

| Case | Hosted FP-RISC | QOS Portable | Portable + block-spin hook |
| --- | ---: | ---: | ---: |
| Same hart | 180 | 292 | 292 |
| Same hart, `sendLinear` of a built value | 180 | 279 | 282 |
| Same hart, bounded inbox | 201 | 305 | 309 |
| Same hart, 1 KiB request | 198 | 299 | 309 |
| Cross hart | 347 | 4,380 | 446 |
| Cross hart, bounded inbox | 352 | 4,468 | 518 |
| Relay of 16 KiB, copy (three hops) | 878 | 1,288 | 1,292 |
| Relay of 16 KiB, move (three hops) | 441 | 766 | 779 |

The hook is `uw hal_block_spin_ns(void) { return 2000; }` appended to
`qos/appside/hal.c`, run once and reverted. It is an experiment, not a patch.

On the hosted runtime the two spin windows separate cleanly (an earlier
program of the same shape, 1,000,000 round trips):

| Hosted, cross hart | ns per round trip |
| --- | ---: |
| Default (both spins on) | 368 |
| Hart-park spin off (`FPR_SPIN_US=0`) | 365 |
| Both off (`FPR_BLOCK_SPIN_NS=0` as well) | 4,398 |

### One endpoint operation

`epbench.fpr` reaches an owner that answers at once, through the real
namespace and the real `EP` client calls.

| QOS Portable | 1 hart | 2 harts |
| --- | ---: | ---: |
| Open, write, close per write (8 messages) | 2,251 ns | 3,608 ns |
| Write on a held handle (2 messages) | 553 ns | 706 ns |

A held write is one correlated `AC.call`. It costs 553 ns where a raw round
trip costs 292 ns: a difference of about 260 ns between these benchmark
paths. Different owners, envelopes and control flow mean this subtraction does
not isolate the call layer. Use matched incremental variants before attributing
that difference to correlation or wrappers.

## Corrections to the original's cost table

| Item | Original claim | Finding |
| --- | --- | --- |
| C1 | Every `send` deep-copies | Small-message timings suggest a substantial fixed path; these runs do not isolate its components or exact per-message cost. |
| C2 | `sendLinear` is an unused fast path, about 220 sites against thousands of `send`s | It has one `.fpr` call site in QOS and none in FP-RISC `std`, against about 740 and 80 occurrences of `send`. It moves only a **received message root**. A locally built value is copied and then consumed (180 against 180). Under the shared memory plane that native apps use, `fpr_arc_movable_root` returns 0, so it never moves there. |
| C3 | A declared inbox bound costs two locks and a charge walk per send | Correct. Measured at about 15 to 20 ns per send uncontended on one hart. |
| C4 | Portable's doorbell is a mutex and a signal per message, with no spin window | Correct as read, but the missing piece that matters is elsewhere: QOS defines no `hal_block_spin_ns`, so the runtime's weak default of 0 applies and an actor about to block never looks again first. |
| C5 | `Svc.read`/`Svc.write` open per operation, about 700 call sites, 8 messages | 8 messages is correct (open 4, operation 2, close 2). The call sites number 58 in tracked `.fpr` files. |
| C6 | The endpoint owner filters all leases on every request | Correct for the deadline-aware owner (`simpleUntil`). The plain owner loop does not. |
| C7 | Admission is O(backlog) under a lock | Correct. `refill` calls it up to `RQ_CAP` times, so one refill is O(`RQ_CAP` x backlog). |
| C8, C9, C11, C12 | Spawn reservations, charge array, launch re-hash, list walks on open | Confirmed at the cited lines. Not measured. |
| C10 | The native storage trampoline polls with no blocking receive, burning a hart for up to 10 s | It polls first and parks via `fpr_actor_sleep_us` only after an empty result, for up to 100 µs capped by the remaining deadline. A reply can already be ready at the first poll. This is a conditional polling penalty, not a burned hart or an unconditional latency floor. |

Two costs the original does not list:

- **Portable's same-hart path is 1.6x the hosted one** (292 against 180 ns).
  Every app-side send and receive goes through the plane's function table
  (`fpr_plane_actors->send_as`), which is one candidate. It is not profiled.
- **The held-call benchmark is about 260 ns slower than raw pingpong**
  (553 against 292 ns). Id generation, envelopes, the `IoV` wrapper, reply
  matching and different owner paths are candidates, not established causes.
  Profile matched paths before treating this as removable call overhead.

## Joint order of work

This is an execution order, not a claim that all projects have measured gains.
The compiler and OS can progress independently until they share an ABI.
Original QOS move numbers remain stable identifiers in the source assessment.

| Stage | FP-RISC | QOS | Promotion gate |
| --- | --- | --- | --- |
| 0 | Record repeatable baselines and matched references | Add counters and repeat pinned/sibling IPC/endpoint runs | Build identity, variability and regression tolerances recorded |
| 1 | Instruction selection and frames | Portable block-spin hook; conditional doorbell separately | Compiler oracles/instruction bounds; IPC, CPU, contention and lost-wake gates |
| 2 | Checked-operation folding/sharing | Deadline-aware blocking C receive | First-trap/effect and spill checks; correlated reply/death/deadline races |
| 3 | Qualify loop modes individually, then combinations | Adopt existing held handles at hot sites; profile fixed call costs | Zero-trip and trap order; handle lifetime/revocation; matched profiling |
| 4 | Coordinate x27 register fuel as an independent ABI change | Validate loader, shared-plane and native boundaries; qualify endpoint slot storage separately | Exact tick traces, mixed-runtime/migration tests, QOS/Pi budgets; access-time lease checks |
| 5 | Investigate allocation stores; support outgoing-message placement only after design | Large-payload ownership transfer, including shared plane | Isolated accounting evidence; lifetime, failure and retained-memory gates |
| Deferred | Chunked fuel after execution-boundary proof | Credits/certificates, descriptor table if justified, scheduler policy, lazy reservations, verification cache, transactions, direct handoff | Separate contracts and validation in this page and the original |

Allocation investigation can proceed independently. Register fuel must land
alone with a compatible runtime/app convention; it must not be bundled with
chunk charging. Endpoint slot storage does not depend on x27. A descriptor
table is conditional on needs remaining after held-handle adoption.

One FP-RISC item is missing from this table because it predates the
fixed-costs page: [filter fusion](../../fprisc/docs/2026-11-06-PERFORMANCE-AT-E138E65.md),
ranked first among the remaining list gaps (202 ms against 24 for fused
`map`). It is independent, semantics-preserving and built on the landed
fusion machinery; it proceeds in parallel with stages 1-3 on the FP-RISC
side and is not blocked by any QOS item.

### Portable block spin, then the doorbell (original Move 1)

On the hosted runtime an actor about to block on an otherwise idle hart
re-checks its mailbox for up to `hal_block_spin_ns()` first
(`spin_until`, `fprisc/runtime/actors.c`). The posix machine sets 2 µs. QOS
sets nothing, so the spin is off. Replies arriving after the receive's final
check can pay block/wake/ship costs; this is not a claim that every reply
requires a kernel sleep.

- Define `hal_block_spin_ns` for Portable. The runtime already guards the
  spin with `hart_quiet`; measure newly arriving work and CPU cost too.
  Keep it configurable and retain zero as a comparison.
- Then make `qosp_hart_ring` signal only when the worker is in the wait, as
  `machine/unix/park.c` does with its `waiting` word. On the hosted runtime
  the park-level spin added nothing once the block spin was on, so the
  spin-in-`park.c` half of the original Move 1 is dropped.
- Keep the latch and the 20 ms cap.
- Leave the native kernel at 0 unless a measurement on the board says
  otherwise. The runtime's own comment gives the reason: `wfi` and an IPI are
  cheap on real harts.

Acceptance: repeated `ipcbench` cross-hart runs target within 2x of same-hart
on Portable, with latency tails, throughput and CPU reported. Measure 60 s idle,
sparse arrivals, saturated traffic, oversubscribed workers and an unrelated
runnable actor. Set allowable CPU/latency regressions from baseline variability
before promotion; an unchanged idle result alone does not qualify spinning.
Record the Pi 4B separately and retain native zero pending board evidence.

The conditional-doorbell patch needs an explicit atomic latch/parked handshake
and memory ordering: message publication, waiter registration, clear/recheck
and sleep must not lose a wake. Exercise rings before/during/after registration,
concurrent rings and timer changes; count signals and verify prompt progress.
Keep the 20 ms cap, but do not use it to mask a lost-wake correctness bug.

### Blocking C receive (original Move 9)

Add a wait that parks the calling ACB until a matching storage reply, target
death, cancellation or deadline. Define how source filtering and correlation
interact with unrelated and late messages; the implementation must not consume
a reply for a later operation. Preserve the 10 s deadline, invalid-reply behavior
and write-side outcome-unknown refusal text. The initial poll can succeed;
remove the sleep-after-empty polling penalty rather than claiming a universal
100 µs floor.

Acceptance: replies before registration, during parking and after wake; sender
or receiver death, cancellation, stale/duplicate replies and reply/deadline
races. State which event wins at the deadline. Count polls/sleeps and measure
native key-value latency distributions before/after, including immediate and
delayed replies. Confirm the parked wait frees the hart for other actors.

### Held handles before a descriptor table (original Move 3)

Count the 58 call sites by execution frequency, adopt `EP.open`/operations/
`EP.close` at hot loops, and measure application workloads. The 2,251-to-553 ns
result demonstrates held handles, not a runtime fd table. Preserve modes,
expiry, explicit close, owner replacement and the intended revocation contract;
extending the lifetime of a stateless operation needs an explicit choice.

If a table is still warranted, define process ownership, slot generations,
rights, reuse/dup, exhaustion and bounded close-on-death cleanup. A runtime fd
is not authenticated IPC: trusted mediation must validate the caller and the
owner must enforce authenticated identity or unforgeable authority, including
attempts to bypass the table with direct messages.

A namespace generation needs coherent protected state or an acknowledged
invalidation protocol. State the revocation linearization point and treatment
of in-flight requests. A local cached generation cannot discover a remote
change on its own. Do not claim all checks disappear on the owner path.

Acceptance: steady-state held operations use two protocol messages; count
invalidation/cleanup traffic separately. Gate wrong-process access, forged
identities, stale/reused fds, close/death races, expiry, owner restart and
operations begun after acknowledged revocation. Compare runtime versus library
table designs only after hot-site adoption establishes the remaining need.

### Endpoint storage and fixed-call profiling

A slot array may defer bulk reclamation, but each accessed handle must still
check generation, identity, expiry and client liveness. Check time at access;
a batch clock cannot silently extend lease authority. Sweep on bounded cadence
and capacity pressure, preserving 64 handles and 60-second expiry.

Gate deadline-minus-one/equal/plus-one without sweeping, dead clients, reused
slots, full capacity with expired slots, close races and existing
`qsysfail`/`filesreclaim` fixtures. Measure allocations and bounded sweep work.

Profile the unexplained same-hart and held-call differences with matched
variants: identical actor placement and owner work, then add id generation,
correlated envelopes, wrappers and matching one at a time. Count allocations,
bytes and messages; instrument or sample the runtime path. Do not attribute
all 110/260 ns to an indirect call or wrapper by subtraction alone.

### Large-message construction and transfer (original Moves 2 and 7)

This replaces "make move the default" and "construction in place".

`sendLinear` cannot make a built value cheaper, because the value lives in
the sender's pool and has to leave it. What removes the copy is building the
value in a slab of its own when the compiler sees it die at the send, and
transferring that slab. This is the sender-owned form the original's open
question 4 asks about, and it reuses what the transfer path already does for
a received root.

- It needs a compiler change (place the allocation), a runtime change (a
  fresh ownerless slab per outgoing message) and, for native apps, a
  transfer path under the shared memory plane.
- Root liveness is insufficient: specify ownership of every reachable child,
  aliases, ARC/slab lifetime, receiver charging, publication ordering and
  sender/receiver death. Retain copying where transfer is not proved safe.
- A slab per message is a candidate, not a universal policy. Compare small and
  large messages, slab allocation overhead and retained memory. Receiver-ring
  construction additionally needs bounded reservations and rollback if the
  sender traps, yields or dies before publication.
- Its gain scales with size. At 1 KiB it is about 20 ns hosted and inside
  run-to-run noise on Portable. The measured copy/move difference is about
  520 ns per three-hop cycle on Portable, not a general per-hop estimate.
- So it ranks below the fixed-path items, and its first users should be the
  large payloads: file contents, frames, listings.

Acceptance: compare copy bytes, allocations/slabs, retained bytes and latency
across payload sizes, root/child aliases and both memory planes. Inject full
inboxes, allocation failure, refusal, cancellation and death before/after
publication. Require exactly-once ownership release and unchanged delivery,
refusal, ordering and resource bounds. Current relay measurements do not
qualify a new outgoing-slab implementation.

### Deferred sender credits and other contracts

Credits may amortize receiver accounting, but preserve both byte and message
limits. Across queued messages, in-flight reservations and outstanding sender
credits, the total must fit the receiver's limits. Define exact variable-size
charging, credit return, cancellation rollback, sender/receiver death, actor
identity reuse and reclamation. Queue publication still requires synchronization;
credits do not make the complete send path free of shared writes.

Unused credits can strand capacity and refuse another sender despite available
physical space. State fairness, reclamation bounds and whether refusal behavior
is preserved. If it changes, propose a separate policy/profile rather than
claiming equivalent mailbox-full behavior. Gate concurrent senders, mixed
payloads, idle credit holders, death, full queues and adversarial retries;
measure contended as well as uncontended cost. Ordinary programs keep current
enforcement until this passes.

The original proposal now supplies the other deferred contracts:

- Certificates need a restricted execution model, exact-image/ABI binding and
  a trusted checker; declarations alone are not concurrency proofs.
- Scheduler structures need a policy and waiting-bound argument. Deterministic
  weights and per-hart epochs do not preserve the existing policy by default.
- Lazy resources must preserve backed capacity for guaranteed admissions, or
  explicitly belong to a best-effort profile with later failure.
- Cached verification needs immutable/protected mapped-byte identity and
  invalidation, not just a content-addressed filename.
- Transaction validation/publication must be serialized or atomic. Known write
  sets need exclusivity, disjointness proofs or serialized ownership before
  conflict checks can be elided; a commit slot only reserves capacity.
- Group commit needs specified acknowledgement and crash-recovery ordering;
  one flush is a storage-dependent measurement target, not an atomicity proof.
- Direct handoff needs ordering, fairness, backpressure and preemption trace
  equivalence, beyond logically charging a queue slot.

## Gates

Two programs are in the tree; their existing checks are smoke checks, not
completion of the qualification gates:

| Program | Command | Reports |
| --- | --- | --- |
| `tests/ipcbench.fpr` | `./qos.py run tests/ipcbench.fpr --harts 2` | ns per round trip: same hart, cross hart, bounded, 1 KiB, relay copy and move |
| `tests/epbench.fpr` | `./qos.py run tests/epbench.fpr --harts 1` | ns per write: open-write-close against a held handle |

Both carry an `#: expect` line and take about ten seconds. Still to add from
the original's list: the debug-profile message counter, `spawn`, `launch`,
`frame` and `idle`.

### Shared measurement and promotion gate

- Record hardware, OS, hart count, affinity, power conditions, exact compiler,
  runtime/QOS commits, flags and instrumentation. Run release-pin and sibling
  builds separately; repeat after a pin update. Separate hosted, Portable,
  QEMU and native/Pi evidence.
- Warm up and interleave repeated baseline/variant runs. Publish run counts,
  medians and variability alongside minima. Preserve current historical tables
  and raw output; new evidence gets its own record. Separate startup and
  steady-state timing and use matched scalar/vectorized/checked references.
- Report per-operation latency distributions (including p95/p99), sustained
  throughput, CPU and memory, under same/cross-hart, sparse, saturated and
  contended loads. Include unrelated runnable actors and idle CPU over 60 s.
- Count protocol messages, copied bytes, allocation/slab activity, reservations,
  block/wake and signal events, flushes and bytes hashed. Keep hot-operation
  counts separate from revocation, refill and cleanup traffic. Measure counter
  overhead with instrumentation off/on.
- Set numeric regression tolerances and baseline noise before promotion. Require
  the corresponding refusal, death, cancellation, race and resource gates,
  plus compiler instruction-bound checks for changes that affect scheduling.
  A good mean or a smoke-test marker does not establish tail or semantic safety.

No new benchmark or runtime behavior is implemented by this review. Counters,
matched variants, repeated runs and adversarial fixtures remain work items.

## Cross-layer notes

- The language-level order the original points to is complete. Its successor
  is [the fixed-costs proposal](../../fprisc/docs/2026-11-06-FIXED-COSTS-PROPOSAL.md)
  in FP-RISC.
- Register fuel is separate from chunked fuel. Before reserving x27, specify
  initialization, authoritative register/memory state and synchronization at
  runtime calls, yield/resume, stack growth, migration, traps, loader, native
  and shared-plane boundaries. Reject incompatible ABI combinations; gate exact
  tick/effect traces and re-qualify QOS/Pi budgets. Chunking stays deferred
  until the FP-RISC execution/yield-boundary proof passes.
- The pin trial to `e138e65` was recorded as a go today while the lock still
  names `1a09f01`. Re-run both programs once the pin moves.

## Open questions

1. Which configurable Portable spin window passes both CPU and latency gates?
   Native/Pi needs a separate decision, not inheritance of the hosted setting.
2. After held-handle adoption, is a descriptor table justified, and which
   boundary enforces identity, revocation and death cleanup?
3. Which component explains the same-hart and held-call differences under
   matched profiling, and how much is avoidable?
4. Which restricted static profile can support queue/resource certificates?
5. What scheduler policy and waiting guarantee would a replacement commit to?

## Addendum: second review, 6 November

Five adjustments from a further review. No new measurement is claimed by
this section beyond the marked items.

1. **Held handles need not wait for stage 3.** Adoption at hot sites is
   application-level, needs no runtime change, is already measured at 4.1x
   in `epbench`, and its gates (lifetime, expiry, explicit close, the
   revocation contract) are specified above. Since stages progress
   independently by this page's own rule, treat held-handle adoption as
   startable immediately, in parallel with stage 1; the descriptor-table
   question stays behind it exactly as written.
2. **Add an IPC floor reference.** Both this page and the FP-RISC
   fixed-costs proposal use matched C references for compute, but the
   message path has none. A same-process two-thread, one-word ring
   ping-pong in C (atomics only, no scheduler) gives the architectural
   floor for a round trip; hosted 180 ns and Portable 292 ns then become
   fractions of a floor instead of absolutes, sizing the total remaining
   IPC headroom before it is spent. It also contextualizes the unexplained
   110 ns same-hart and 260 ns held-call gaps.
   *Measured, 6 November* (`tests/ipcfloor.c`, raw output in
   [evidence](evidence/2026-11-06-ipc-floor.txt), same host class): spin
   floor 106-127 ns median per round trip; a parked condvar ping-pong
   brackets blocking-style doorbells at 4.4-6 us quiet (macOS-specific;
   load-sensitive to 12.6 us). Against the spin floor, hosted same-hart is
   about 1.5x - the hosted message path has only tens of nanoseconds of
   headroom left - while Portable's default cross-hart 4,380 ns is ~35x
   and sits inside the parked band, consistent with a blocking wake per
   message; the block-spin hook's 446 ns leaves that band at ~3.5x. This
   reframes the remaining IPC work as almost entirely a Portable problem.
3. **A direct probe for the 110 ns same-hart gap, before the harness.**
   The plane function table (`fpr_plane_actors->send_as`) is the stated
   candidate. A one-off devirtualized build (direct call in place of the
   table load), run exactly like the block-spin hook and reverted after,
   either collapses the gap - attribution without the matched-variant
   harness - or exonerates the table and better targets that harness.
   *Examined and partly measured, 6 November*: the devirtualized build is
   not a two-line hook - `fpr_plane_export` binds the exporting image's
   implementation into the table, so on Portable the callee lives in the
   kernel image and cannot be named from the app image; the table is the
   cross-image contract, not an avoidable dispatch. A micro-measurement of
   the dispatch itself (direct call versus a volatile function pointer,
   200 M calls, this host) shows parity at 0.8-0.9 ns per call: a
   monomorphic indirect call is free when predicted. The table load and
   call therefore cannot explain 110 ns; what the table costs is the lost
   inlining and cross-function reasoning across the boundary. The
   matched-variant harness should start with the wrapper layers (id
   generation, correlation envelopes, message copying) and treat the
   dispatch as exonerated. Local `ipcbench` baseline for future probes on
   this machine class: same 341 ns, cross 6,241 ns (busier machine than
   the recorded runs).
4. **The outgoing-slab transfer reuses an existing compiler analysis.**
   "Place the allocation in a slab of its own when the compiler sees it
   die at the send" needs precisely the capture-aware single-use proof the
   checked List-fusion float already computes and has run in production
   since 2 November (with its trap-safety hardening). The new work is the
   placement decision and the runtime transfer, not the liveness fact;
   the estimate should reflect that. It is also the same ownership-gated
   representation story as the unboxing proposal's B6 addendum, and should
   cross-link it.
5. **Adaptive spin-then-park as the configurable shape.** For the block
   spin, consider a decaying spin window rather than one fixed value: on
   Portable the harts are OS threads, so the idle-CPU gate is the binding
   constraint, and a spin that decays to park respects it by construction
   while keeping the fast case. Keep zero as the comparison arm either way.

## Limits of this evidence

- One machine, arm64 macOS, QOS Portable only. Nothing here is measured on the
  native kernel, under QEMU or on the Pi.
- Each configuration ran once or twice. Two Portable runs of the same program
  differed by up to 12% on single rows (335 against 299 ns for the 1 KiB
  case).
- The compiler is the sibling checkout, not the release pin.
- The block-spin figure comes from a temporary two-line edit, reverted after
  one run. Idle CPU with the spin on was not measured.
- Blocking receive, endpoint slot storage and deferred architectural changes
  rest on source/design arguments; their implementations have not been measured.
- The hosted spin table comes from an earlier program timed as a whole
  process, not from `ipcbench`.
