# Toward a zero-overhead QOS: remaining taxes and where to remove them

Date: 2026-11-06. Kind: source assessment and ranked proposal. No runtime
change is implemented by this page.

Review update: the measurements and current work order are in the
[amended proposal](2026-11-06-ZERO-OVERHEAD-OS-AMENDED.md). The original move
numbers below remain stable identifiers, not execution ranks. This page now
carries the corrected contracts too; proposals requiring new policy or proofs
are explicitly deferred. Historical baselines remain unchanged.

Baseline: QOS `03ccd4a`. FP-RISC pin as recorded in `fprisc.lock.json` is
`1a09f0141c7bdb7ed022d7fcc1876f70666f661d`; the sibling checkout used for
source inspection was `95e2fbc`, which contains the
[26 October baseline](../../fprisc/docs/2026-10-26-PERFORMANCE-BASELINE.md)
and the [6 November remeasure](../../fprisc/docs/2026-11-06-PERFORMANCE-AT-E138E65.md).
Line numbers below are as of that baseline.

This page answers one question: with actor message passing, URL addressing and
UNIX-style `open`/`read`/`write`/`close`, protocol-level transactions and
upfront resource declarations kept exactly as they are, what is left to pay for
and how is each item removed? The language-level zero-overhead order is
separate and lives in FP-RISC:
[the follow-up inventory](../../fprisc/docs/2026-10-31-ZERO-OVERHEAD-FOLLOWUPS.md)
and [the unboxing proposal](../../fprisc/docs/2026-11-01-UNBOXING-ZERO-OVERHEAD-PROPOSAL.md).

## The thesis

The remaining overhead is structural, not semantic. It comes from four habits,
each of which is a candidate for replacement subject to the contracts below:

1. **Re-verifying at every operation what could be proved once.** A declaration
   that was checked at admission is checked again on every send.
2. **Re-deriving at every operation what could be bound once.** `open` is the
   authorization event; callers below it still re-resolve names and re-walk
   grant lists.
3. **Copying values that could be moved or built in place.** `send` deep-copies;
   the runtime already has a zero-copy transfer that protocol code does not use.
4. **Waking, flushing and hashing per message or per launch** what can be
   batched or amortized.

Sections 2 and 3 are the same principle applied at the OS layer that
FP-RISC applies at the language layer: **decide once, then pay only for the
work itself.**

## 1. What already qualifies and must not regress

- The endpoint contract is already the right shape. A client asks the namespace
  to `open`; the namespace authorizes, resolves the longest registered prefix,
  and forwards the envelope; from then on traffic is direct and the namespace is
  out of the conversation ([ep.fpr:1-30](../programs/mods/ep.fpr)).
- The capability gate is a list check **at open**, not per operation
  ([svc.fpr:81](../programs/mods/svc.fpr)).
- Spawn admission is already a transaction: entry copy, stack, slab, bucket
  arrays, channels and ACB are reserved before the actor is published, with a
  rollback on every partial prefix (`a_spawn_heap`, `admission_rollback`).
- Long-lived service loops already amortize heap reclamation with `tidy`
  (a boundary only when the heap has doubled past its live size,
  [std/actor.fpr:289](../../fprisc/std/actor.fpr)).
- The host runtime already spins before sleeping; the profile found sleep+wake
  at roughly 90% of a cross-hart round trip
  ([machine/unix/park.c:11](../../fprisc/machine/unix/park.c)).
- Same-hart wake already hands the actor the next slot without a cross-hart
  ship (`wake_hint` in `wake`, [actors.c:1883](../../fprisc/runtime/actors.c)),
  and the sender/consumer cache-line split took cross-hart streaming from
  11.5M to 20M messages/s ([XHART](../../fprisc/docs/2026-10-01-XHART.md)).

## 2. Where the cost is today

| # | Cost | Location | Kind |
|---|---|---|---|
| C1 | Every `send` deep-copies the message graph and allocates a slab | `fpr_send_as` ([actors.c:2770](../../fprisc/runtime/actors.c)), `fpr_msg_copy_to` | Per message |
| C2 | `sendLinear` moves a received root with no copy, but built values still copy and shared-plane memory disables this transfer | `a_send_linear` ([actors.c:2871](../../fprisc/runtime/actors.c)) | Unused fast path |
| C3 | A declared inbox bound forces **two locks and a charge walk on every send**, even with one sender | `inbox_reserve` ([actors.c:802](../../fprisc/runtime/actors.c)) plus `locked = shared \|\| inbox_max_messages` in `ring_push` ([actors.c:2726](../../fprisc/runtime/actors.c)) | Per message |
| C4 | Portable worker wake is a mutex and `pthread_cond_signal` per message, with no spin window | `qosp_hart_ring` ([park.c:70](../qos/portable/park.c)) reached from `hal_ipi_send` | Mutex/signal path per ring; syscall behavior not counted |
| C5 | `Svc.read`/`Svc.write` do open, one operation, close | `route`/`viaNs`/`viaOp` ([svc.fpr:81](../programs/mods/svc.fpr)); 58 tracked `.fpr` call sites in the amended assessment | 8 messages per op |
| C6 | The deadline-aware `simpleUntil` owner filters leases and allocates a list on every request | `untilStep`, `liveLeases` ([epservice.fpr:129](../programs/mods/epservice.fpr)) | Per message, O(handles) |
| C7 | Admission walks the whole backlog under a lock, runs an LCG per entry, takes a machine-wide atomic, and scans the run queue for duplicates | `select_backlog` ([actors.c:1132](../../fprisc/runtime/actors.c)), `refill` ([actors.c:1192](../../fprisc/runtime/actors.c)) | Per admitted actor, O(n) |
| C8 | Every actor reserves a 128 KiB stack and an 8 KiB channel block at spawn | `FPR_STACK_SZ` ([actors.c:62](../../fprisc/runtime/actors.c)), `chb_take` | Per actor |
| C9 | A bounded actor also reserves a 4 KiB charge array | `INBOX_CHARGES_SIZE` ([actors.c:842](../../fprisc/runtime/actors.c)) | Per actor |
| C10 | Native storage polls, then sleeps up to 100 µs after an empty poll, within a 10 s deadline | `qos_store_call` ([process.c:153](../loader/process.c)) | Per native storage op |
| C11 | Every plugin attach re-hashes the whole image although the digest is content-addressed | [host.c:300](../qos/portable/host.c), [host.c:315](../qos/portable/host.c) | Per launch, O(image) |
| C12 | Repository-style scans on open: `EP.resolve`, `EP.ownerOf`, `EP.allowed` walk lists | [ep.fpr:199](../programs/mods/ep.fpr), [ep.fpr:219](../programs/mods/ep.fpr), [ep.fpr:232](../programs/mods/ep.fpr) | Per open |

C1, C3, C4 and C6 are on the message path itself. C5 and C12 are the reason an
open is expensive enough to matter. C8 and C9 are why an idle actor is not free.

## 3. Current order and stable move identifiers

Use the amended proposal's [joint order](2026-11-06-ZERO-OVERHEAD-OS-AMENDED.md#joint-order-of-work)
for execution. The old move numbers are retained for links and discussion:

| Order within QOS | Work | Original move | Required boundary |
| --- | --- | --- | --- |
| 0 | Repeatable measurements and counters | Section 5 | Baseline and regression tolerances before promotion |
| 1 | Portable block spin, then conditional doorbell | 1 | Lost-wake safety, CPU and contention gates |
| 2 | Blocking native storage receive | 9 | Reply/death/deadline races and correlation |
| 3 | Held handles at hot sites; profile fixed call costs | 3 | Explicit lifetime and revocation; table only if justified |
| 4 | Endpoint slot storage and lazy reclamation | 4 | Expiry and liveness checked on access |
| 5 | Large-message construction and ownership transfer | 2 + 7 | Lifetime, refusal, accounting and shared-plane contract |
| Deferred designs | Credits/certificates, scheduler, lazy resources, verification cache, transactions and direct handoff | 5, 6, 8, 10, 11, 12 | Separate proofs and policy decisions below |

### Move 1: Portable block spin, then conditional doorbell

The measured benefit comes from `hal_block_spin_ns` before actor blocking,
not a new spin in `qos/portable/park.c`. Qualify a configurable Portable hook
using the hosted 2 µs setting as a candidate, not a universal default. The
runtime's `hart_quiet` check avoids deliberately spinning behind queued work,
but arriving work and CPU cost still need measurement. Native stays at zero
pending separate board evidence.

Then optimize `qosp_hart_ring` to signal a waiting worker only. Specify the
atomic latch/parked handshake and memory ordering across publish, clear, waiter
registration and sleep. A timeout fallback does not excuse a lost-wake race.
Keep the 20 ms fallback and timer behavior.

Acceptance: repeated matched IPC runs, latency distributions and throughput;
60 s idle CPU, sparse requests, sustained traffic and unrelated runnable actors;
adversarial ring-before/during/after-wait and timer races with no lost wake.
Record signal counts, CPU and Pi results separately. See the amended gate.

### Move 2: ownership transfer, not automatic move-by-liveness

The runtime can transfer an eligible received root without copying. A locally
built value still copies through `sendLinear`; shared-plane memory currently
disables the movable-root test. A dead value at a send is not by itself proof
that its storage is transferable. Do not change default `send` semantics on
that basis, including dead-target refusal and ownership consumption.

Combine this with Move 7 as a later large-payload design. Prove root/child
alias lifetimes, backing-slab ownership and receiver accounting. Retain copying
for unsupported values. Gate success, refusal, cancellation and death at every
transfer boundary with exact ownership and no leaks or double release. The
amended proposal preserves the relay timings without treating them as a result
for compiler-created outgoing slabs.

### Move 3: held handles first; descriptor table only if justified

The amended source count is 58 tracked `Svc.read`/`Svc.write` call sites, not
about 700. Profile their frequency and migrate hot loops to existing `EP.open`,
repeated operations and `EP.close` before introducing a runtime table. The
benchmark establishes the value of held handles, not the necessity of a table.
Holding a handle also extends its lifetime: specify mode, expiry, close,
revocation and owner-replacement behavior rather than silently caching a
stateless operation by URL alone.

If needed, a process-local table maps `(fd, slot generation)` to
`(owner, handle, rights, namespace generation)`. Define descriptor reuse, dup,
close, process death, bounded table exhaustion and cleanup ownership. Cleanup
must release resources even when the owner is dead or refuses a close; it is
not free merely because the table lives in the runtime.

An fd does not authenticate IPC. Trusted code must validate the calling process
and translate the descriptor, and the owner must receive an authenticated
identity or unforgeable authority. Direct messages carrying a claimed `from`
remain a bypass unless the receiving boundary enforces the same rule. See the
[existing design alignment](2026-10-18-QOS-DESIGN-ALIGNMENT.md).

Specify a coherent revocation mechanism: shared protected generation state or
acknowledged invalidations, including races with open, operation and owner
replacement. State a linearization point for revocation and how in-flight work
is handled. A client-local cached generation cannot discover a remote update
without such a mechanism.

Acceptance: two protocol messages for a steady-state held operation, with
invalidation traffic counted separately; wrong-process and forged identity
refused; stale/reused descriptors refused; operations begun after acknowledged
revocation refused; close/death/owner-restart races release resources within a
stated bound. Compare held-handle adoption against a table prototype before
choosing runtime versus library ownership.

### Move 4: slot storage with lazy reclamation, strict access checks

Replace per-request lease-list rebuilding in `simpleUntil` with bounded slot
storage. Sweep dead or expired slots on a bounded cadence or capacity pressure,
but validate the selected handle's generation, expiry, client identity and
liveness on every access. Lazy reclamation must not extend a lease's authority.
Capacity pressure must reclaim eligible slots before reporting exhaustion.
Preserve the 64-handle and 60-second limits and close/cancellation behavior.

Acceptance: expiry at just before/equal/after the deadline without a sweep;
dead-client access; stale slot reuse; full capacity with reclaimable leases;
close races and existing `qsysfail`/`filesreclaim` legs. Record sweep work and
allocation counts, with no lease-list allocation per request.

### Move 5: certificates remain a separate proof project

Policy declarations are limits, not proofs of conformance. Existing work and
allocation analyses do not establish general concurrent queue depth, peak live
heap or maximum actors. Keep enforcement for ordinary programs. First profile
contended bounded-inbox charging; the amended uncontended cost is only about
15 to 20 ns per send.

For a restricted static profile, specify the supported program model,
environment/sender assumptions, proof rules and trusted checker. Bind a
certificate to the exact image, compiler semantics and runtime ABI; reject
missing, forged, stale and inconsistent certificates. An archive field or
compiler annotation alone is not a proof. Unknown bounds fail closed.

Only remove a runtime check where a validated proof covers all executions,
including cancellation, external input and concurrent senders. Preserve checked
fallbacks outside that profile. Gate adversarial overruns, external senders,
proof mismatch and refusal semantics, with the existing admission fixtures.
Credits are an alternative experiment, with a separate contract in the amended
proposal; neither mechanism is authorized as a default-path deletion yet.

### Move 6: scheduler structures need a new policy argument

Profile backlog selection, `g_adm` contention and duplicate scans first.
Removing a redundant scan with a proved insertion invariant can be isolated
from changing selection. A heap is O(log n); bucket-array O(1) claims need
bounded bucket count, occupancy, overflow handling and a bound on advancing
empty epochs.

Deterministic weighted queues are not the existing weighted reservoir policy.
Per-hart epochs are not a global epoch without a skew and migration argument.
Specify aging, fairness, starvation bounds and the admission linearization
point; re-derive the waiting/instruction bound for any changed policy. Do not
claim the same WCET expression with only a smaller constant.

Acceptance: scheduler probes at 1/4/8 harts and 1/32/1024 ready actors; skewed
weights, churn, migration and starvation adversaries. Check distributions,
maximum wait and formal bound assumptions, not just current fixture ordering.
Keep the existing policy until that argument and measured benefit pass.

### Move 7: large-message construction and transfer

Prefer investigating sender-owned outgoing slabs before reserving receiver
ring slots during construction. The latter can hold capacity indefinitely if
construction traps, yields or is cancelled. Either design needs bounded
reservation, rollback, publication ordering, receiver-death handling, lifetime
and resource-accounting rules. A size proof alone establishes none of these.

Outgoing slabs need compiler placement and whole reachable-graph ownership,
not just root liveness. Shared children need retained ownership or copying;
shared-plane apps need an explicit transfer path. Compare total copy bytes,
allocation/slab overhead and retained memory across payload sizes before
choosing one slab per message as a policy. See the amended transfer gate.

### Moves 8 to 12: distinct deferred contracts

- **8. Lazy reservations.** Separate best-effort actors from guaranteed
  admissions. Small initial stacks or deferred channels can move failure from
  spawn to later execution. Guaranteed actors retain backed capacity or an
  equivalent reservation; growth paths alone do not preserve admission.
  Gate resource exhaustion after spawn, rollback, repeated growth and death,
  measuring committed and reserved bytes separately.
- **9. Blocking C receive.** Native storage already sleeps after an empty
  poll, so it does not burn a hart or impose an unconditional 100 µs floor.
  Add a deadline-aware correlated wait that parks the ACB; preserve the 10 s
  deadline and outcome-unknown refusals. Gate replies before/during parking,
  death, cancellation, stale replies and reply/deadline races. Measure actual
  poll/sleep counts and latency before and after.
- **10. Verify at install.** A digest-shaped name does not guarantee immutable
  bytes. Cache verification only for an immutable/protected artifact identity
  bound to the exact mapped bytes and validation policy. Revalidate changed
  or untrusted bytes; invalidate across replacement and policy changes. Gate
  tampering, path replacement, install/launch races and invalidation. Treat
  shared `std` code as a separate ABI, relocation and lifetime design.
- **11. Transactions.** See section 4; atomic publish, conflict handling and
  durable recovery are distinct contracts.
- **12. Direct handoff.** Defer until queue ordering, mailbox backpressure,
  fairness, cancellation and preemption equivalence are specified. Charging a
  logical queue slot alone does not establish equivalence. Gate mixed queued
  traffic, full mailboxes, death and a third runnable actor against the queued
  implementation's traces.

## 4. Transactions and atomic replacement

The [high-value list](2026-10-20-HIGH-VALUE-NEXT.md) names atomic replacement as
its first item, and the current `replace` mode tombstones a file before the new
bytes arrive. Candidate mechanisms reduce bookkeeping, subject to separate
visibility and durability contracts:

- **Publish, don't overwrite.** A writer builds the new value privately and
  swaps a pointer; readers keep the old version alive by reference. There is no
  empty-file window and no reader lock. This is the same discipline the runtime
  already uses to promote a message to shared on send.
- **Group commit.** Amortize flush and commit-record costs across a batch,
  with atomicity only under a specified recovery protocol. Define whether `write`
  acknowledges volatile publication or durability; do not silently weaken an
  existing acknowledgement. Ordering may require data and commit barriers,
  so one flush is a hypothesis to measure against the storage contract.
- **Validate generations, not copies.** Where a transaction's read set must be
  checked, record `(resource, generation)` words and validate them in one
  message at commit. Validation and publication must be serialized or atomic
  with respect to competing commits; otherwise both can validate stale state.
  State isolation, generation-wrap handling, retry and outcome-unknown rules.
- **Declared write sets.** Where the compiler can see a transaction's write set,
  reserve capacity at admission. Eliding conflict detection additionally needs
  exclusive ownership of the affected resources, serialized ownership through
  commit, or a proof that concurrent write/read sets cannot conflict. A known
  write set or a reserved commit slot alone is insufficient.

Keep the [reliability draft's](2026-10-06-FP-RISC-QOS-Reliability-Draft.md)
distinction: a protocol transaction is a conversation with a lifetime and an
outcome, not database atomicity. Nothing above adds isolation, rollback or
durability to the kernel.

Acceptance: interrupt at each boundary and observe the entire previous or the
entire new value; concurrent readers never see a partial replacement;
recovery honors the documented acknowledgement after power loss. Exercise
competing overlapping/disjoint transactions, stale generations, validation-to-
publish races, cancellation and every persistence boundary. Measure flushes and
barriers per batch rather than assuming one flush suffices for all devices.

## 5. Gate it with invariants, not impressions

The FP-RISC benches measure the language. The OS contract needs its own.
Apply the amended proposal's shared measurement gate: repeated interleaved
runs, medians/variability alongside minima, separate release-pin/sibling
builds, latency tails, contention and CPU use. Historical tables are not new
qualification results.

| Bench | Records |
|---|---|
| `ipc_roundtrip` | ns per `call`, same hart and cross-hart, payloads 0/8/64/1024 |
| `ipc_stream` | messages/s one-way, with the ring and copy counters |
| `file_io` | open/read/write/close at 1..10^5 ops, bytes/s and **messages per operation** |
| `spawn` | actors/s and reserved bytes per live actor |
| `launch` | attach to first frame, bytes hashed, page faults |
| `frame` | p99 frame time and CPU per frame |
| `idle` | CPU per idle hart over 60 s |

Two rules make these gates rather than dashboards:

1. **Message counts are part of the specification.** "A cached read is two
   messages; an uncached one is eight" is a testable statement, in the same
   spirit as the existing per-function instruction ceilings. Instrument the
   runtime with a debug-profile counter, as `FPR_COST_PROBE` already does, and
   assert the count.
2. **Every fold gets a refusal test as well.** A cached descriptor must be
   refused after revocation; a proved declaration must be refused when the
   certificate is missing; a batched commit must be refused when its generation
   is stale.

## 6. What not to do

- Do not let a cached descriptor become a way to skip authorization. Cache the
  *result* of authorization, with a generation that revocation invalidates.
- Do not lower `call` to an in-line function call without deciding the
  observable differences: mailbox-full backpressure, queue ordering, and
  fairness all change. Move 12 requires trace equivalence as well as a blocking
  caller and a logically charged queue slot.
- Do not make a declared bound advisory again to speed a test. Move 5 may
  remove a check only under a validated proof; general programs keep runtime
  enforcement. Credits must not silently change mailbox-full behavior.
- Do not claim a WCET from any of this until sleep/wake, flush and device
  completion have bounds. The audit's caution about `tau` in admissions still
  stands ([architecture audit](2026-09-29-QOS-ARCHITECTURE-AUDIT.md)).

## 7. Open questions

- After hot callers use held handles, is a descriptor table still justified?
  If so, which runtime/library boundary enforces process identity, revocation
  and bounded death cleanup?
- Can the certificate be checked by the existing interval and bounds passes
  without a second analysis, or does it need a separate whole-program pass?
- Is a static-scheduler profile worth having for the fully declared case — a
  fixed actor set with run-to-completion dispatch and an explicit admission
  proof? What policy and waiting guarantee would it provide?
- For Move 7, is the receiver's ring the right allocation site, or should the
  sender own the slab and hand the whole slab over at publish (fewer partial
  writes, one ARC operation for a batch)?
