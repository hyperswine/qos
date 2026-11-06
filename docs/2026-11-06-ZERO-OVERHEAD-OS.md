# Toward a zero-overhead QOS: remaining taxes and where to remove them

Date: 2026-11-06. Kind: source assessment and ranked proposal. No runtime
change is implemented by this page.

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
each of which can be replaced without weakening a contract:

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
| C2 | `sendLinear` moves a received root with no copy, but protocol code rarely uses it (about 220 sites against thousands of `send`s) | `a_send_linear` ([actors.c:2871](../../fprisc/runtime/actors.c)) | Unused fast path |
| C3 | A declared inbox bound forces **two locks and a charge walk on every send**, even with one sender | `inbox_reserve` ([actors.c:802](../../fprisc/runtime/actors.c)) plus `locked = shared \|\| inbox_max_messages` in `ring_push` ([actors.c:2726](../../fprisc/runtime/actors.c)) | Per message |
| C4 | Portable worker wake is a mutex and `pthread_cond_signal` per message, with no spin window | `qosp_hart_ring` ([park.c:70](../qos/portable/park.c)) reached from `hal_ipi_send` | Syscall per message |
| C5 | `Svc.read`/`Svc.write` do open, one operation, close | `route`/`viaNs`/`viaOp` ([svc.fpr:81](../programs/mods/svc.fpr)); about 700 call sites | 8 messages per op |
| C6 | The endpoint owner filters all leases and allocates a list on **every** request | `untilStep`, `liveLeases` ([epservice.fpr:129](../programs/mods/epservice.fpr)) | Per message, O(handles) |
| C7 | Admission walks the whole backlog under a lock, runs an LCG per entry, takes a machine-wide atomic, and scans the run queue for duplicates | `select_backlog` ([actors.c:1132](../../fprisc/runtime/actors.c)), `refill` ([actors.c:1192](../../fprisc/runtime/actors.c)) | Per admitted actor, O(n) |
| C8 | Every actor reserves a 128 KiB stack and an 8 KiB channel block at spawn | `FPR_STACK_SZ` ([actors.c:62](../../fprisc/runtime/actors.c)), `chb_take` | Per actor |
| C9 | A bounded actor also reserves a 4 KiB charge array | `INBOX_CHARGES_SIZE` ([actors.c:842](../../fprisc/runtime/actors.c)) | Per actor |
| C10 | The native app storage trampoline polls with no blocking receive, for up to 10 s | `qos_store_call` ([process.c:153](../loader/process.c)) | Per native storage op |
| C11 | Every plugin attach re-hashes the whole image although the digest is content-addressed | [host.c:300](../qos/portable/host.c), [host.c:315](../qos/portable/host.c) | Per launch, O(image) |
| C12 | Repository-style scans on open: `EP.resolve`, `EP.ownerOf`, `EP.allowed` walk lists | [ep.fpr:199](../programs/mods/ep.fpr), [ep.fpr:219](../programs/mods/ep.fpr), [ep.fpr:232](../programs/mods/ep.fpr) | Per open |

C1, C3, C4 and C6 are on the message path itself. C5 and C12 are the reason an
open is expensive enough to matter. C8 and C9 are why an idle actor is not free.

## 3. The moves, ranked

Ordered by (impact x confidence) / effort. Each row keeps every contract named
in the introduction.

| Rank | Move | Contracts kept | Effort |
|---|---|---|---|
| 1 | Spin-then-park, and ring only a parked worker | Doorbell only; no message semantics | S |
| 2 | Make move the default for request and reply payloads | Same messages, same order; ownership moves | M |
| 3 | Per-process descriptor table so `Svc` stops opening per operation | `open`/`read`/`write`/`close` unchanged; open stays the only authorizer | M |
| 4 | Amortize endpoint-owner bookkeeping: slot array and lazy sweep | Lease, expiry and `close`-is-the-cancellation contract unchanged | S |
| 5 | Admission certificates: proved declarations, no per-send charge | Declarations become stronger; a checked profile remains | L |
| 6 | O(1) scheduler selection, no global admission atomic, no duplicate scan | Same weighted and aged policy, same WCET expression | M |
| 7 | Construction-in-place messaging | Same delivery; the copy disappears | L |
| 8 | Lazy reservations: small start stack, channels on first send | Growth paths and refusal behavior already exist | S |
| 9 | Blocking `fpr_receive_from_c` for the native trampoline | Same reply contract; the caller parks instead of spinning | S |
| 10 | Verify at install, not at launch; share `std` code across apps | Integrity claim moves earlier, not away | M |
| 11 | Transactional layer: copy-on-write publish, group commit, generation validation | The protocol-level transaction contract is unchanged | M |
| 12 | Same-hart direct handoff for correlated `call` pairs | Only where the caller already blocks in `call`; see risks | L |

### Move 1: charge the doorbell only when someone is asleep

`qos/portable/park.c` waits directly in `pthread_cond_timedwait` and the ringer
takes the mutex and signals unconditionally. The host runtime's
`machine/unix/park.c` already does the right thing: spin for a bounded window
before sleeping, and only enter the kernel when the peer has not answered.

Do the same on the app side:

- The ringer tests a single atomic "parked" word and performs a store; it takes
  the mutex and signals only when the word says a worker is in the wait.
- The waiter spins with `isb`/`pause` and a doubling gap (the host's
  `FPR_SPIN_GAP`), then double-checks the latch before the first timed wait.
- Keep the latch and the 20 ms cap: a missed ring must cost latency, never a
  hang.

Acceptance: a two-worker pingpong measured with and without the spin, recording
messages/s and the number of `pthread_cond_*` calls; no case where a message is
held after the cap. The host runtime's own numbers show this is the largest
single Portable item, and this change makes the app side match it.

### Move 2: move, don't copy

`AC.call` pays two deep copies and two allocations: one for the request, one for
the reply. The runtime already supports the zero-copy transfer — a received
root's single standing count changes hands, and a relay chain is zero-copy end
to end ([sendLinear contract](../../fprisc/runtime/actors.c)).

Two levers, in order of safety:

1. **Compiler-inserted move.** Escape facts already exist from closure
   conversion. Where the payload dies at the send, emit the move form.
2. **Library-level linear send.** Make `send` on a value the checker has
   consumed lower to the move, and keep an explicit copying form for "I still
   own this". Protocol replies are the obvious first users: `AC.reply` builds a
   value that is dead immediately afterwards.

Keep the observable difference honest: `sendLinear` releases the value on a
dead target instead of refusing it. That is already its documented contract, and
it is the right one for a reply.

Acceptance: a message count and `fpr_alloc` count per `call` in the debug
profile (see section 5) drops from two copies to at most one, with the existing
death, refusal and stale-reply tests green.

### Move 3: a descriptor table, not an open per operation

`Svc` is a stateless shim, so it cannot cache a lease, and every one of the
≈700 read/write sites pays the open handshake. The endpoint design's own
promise is the opposite: "from here on the namespace is out of the
conversation".

Give each process an fd-sized integer that the client-side library maps to
`(owner, handle, generation)`:

- `open` returns the fd; it is the only operation that names a URL.
- `read`, `write` and `close` carry the fd. No string, no prefix match, no
  grant walk, no lease list on the owner's per-request path.
- A namespace generation, bumped on `NsUnreg`/`NsGrant`, invalidates cached
  entries in one compare. The owner still refuses a handle it does not hold.
- Process exit closes the table, which makes `close`-on-death structural
  instead of a sweep of claimed client keys.
- `dup` and `seek` become library protocol on top of the same table, not new
  kernel primitives.

This is a correctness improvement as well as a cost one: today the lease owner
is a key the client *claims*, and the IPC exposes no authenticated sender, so a
client can name another client's key
([design alignment](2026-10-18-QOS-DESIGN-ALIGNMENT.md)). An fd the runtime
issued removes that class of confusion for every holder that goes through the
table.

Acceptance: a cached `read` is exactly two messages, measured; revocation of the
URL makes the next operation refuse rather than reach a retired owner; a process
that dies leaves no lease behind.

### Move 4: stop sweeping sixty-four leases per request

`untilStep` in the deadline-aware endpoint owner recomputes the live lease list
before dispatching any message. Keep handles in a fixed slot array with an
expiry word, sweep on a bounded cadence (every N requests or on capacity
pressure), and read the clock once per batch. The 64-handle and 60-second
limits, and the "abandoned open expires" behavior, are unchanged.

Acceptance: the existing `qsysfail` and `filesreclaim` legs, plus a request
count in the debug profile showing no per-request list allocation.

### Move 5: declarations become proofs

The [resource-accounts draft](2026-10-03-RESOURCE-ACCOUNTS.md) already requires
that accounting not add a round trip per allocation, function entry or send.
C3 is where the current runtime breaks that rule: *declaring* a message bound
costs two locks and a charge computation on every send.

Split the two meanings the declaration currently carries:

- **Policy**: what the app is allowed to use. Checked once, at admission,
  against the manifest and the parent account.
- **Proof**: what the compiler already computes — work and allocation bounds,
  and now stack depth, peak live heap, maximum message size and maximum live
  actors.

Then:

- Size each ring from the proved queue depth. A full ring becomes unreachable,
  not refused, so the "mailbox full" branch is a debug-profile assertion.
- Reserve the proved heap/stack once at spawn. Per-allocation cap checks
  disappear; the buddy and the actor's slab do the only enforcement that is
  still needed.
- Delete `inbox_reserve` and the per-ring charge arrays from the hot path in the
  default profile, and keep them in a `checked` profile for unannotated or
  untrusted apps.

Nothing in the user-visible contract changes: an app that exceeds its
declaration still fails, one step earlier and more precisely, with the compiler
or the loader naming the violated bound. The gain is that the *conforming* app
pays nothing for the declaration at run time, which is the whole point of
declaring it.

Prerequisite: the certificate must be a claim by the build, not a trusted
annotation. Emit it as data in the archive, and have the loader refuse a
manifest whose certificate is absent or inconsistent with the image.

Acceptance: the current admission-refusal fixtures keep their names and
outcomes; a benchmark shows declared and undeclared builds within noise of each
other on the message path; the checked profile still catches the same
deliberate overruns.

### Move 6: make admission constant-time

`select_backlog` walks every backlog entry under `bl_lock`, evaluates the aged
tier and a weighted reservoir, and `refill` then takes the machine-wide
`g_adm` atomic and scans the run queue for a duplicate.

Replace the walk with structures that answer the same questions:

- Aging by deadline: an EDF bucket array or min-heap keyed by `ready_at + tau`.
  A bucket array over the admission epoch is O(1) and bounded.
- Weighting by fair queuing: one FIFO per weight class, drawn by a small
  deterministic schedule. Same long-run shares, no per-entry LCG.
- Admission epochs per hart, published with a bounded skew, instead of one
  contended global counter. The WCET expression keeps its shape; only the
  constant term shrinks.
- The duplicate-entry check belongs to the queue insert, where the invariant is
  already known, not to a scan on every admission.

Acceptance: the scheduler probe's wait distribution and `g_max_wait` at 1, 4 and
8 harts with 1, 32 and 1024 ready actors; no change in fairness ordering for the
existing fixtures.

### Move 7: build the message where it will be read

Once move is the default, the remaining copy is *construction*. A sender with a
proved message size can reserve its slot in the receiver's ring and construct
directly into it, then publish the tail. `send` becomes: reserve, write words,
release-store, wake. No slab, no ARC promotion, no copy.

This is the OS analogue of the unboxing work: the abstraction (a message with a
typed shape) is unchanged, and the mechanism is what a systems programmer would
have written. It depends on Move 5 for the size proof.

### Moves 8 to 12, briefly

- **8. Lazy reservations.** The channel block and the 128 KiB start stack are
  paid at spawn whether or not the actor talks or recurses. Start smaller and
  use the growth paths that already exist (`fpr_stack_grow`, ring doubling), so
  a leaf actor costs kilobytes rather than a hundred.
- **9. A blocking C receive.** Only the non-blocking `fpr_receive_from_now_c`
  exists, so the native trampoline polls for its storage reply. A blocking
  variant that parks the calling ACB turns a burned hart into a normal wait, and
  needs no protocol change.
- **10. Verify once.** The image digest is content-addressed, so a second hash
  of the same bytes proves nothing new. Record the verification with the
  installed artifact and map/relocate on launch; keep re-hashing for artifacts
  that arrive unverified.
- **11. Transactions without per-operation bookkeeping.** See section 4.
- **12. Direct handoff for correlated calls.** Where both actors are known and
  pinned to one hart, and the caller already blocks inside `call`, the reply
  needs no queue round trip. This is the highest ceiling and the highest risk:
  mailbox-full backpressure and fairness are observable, so it may only be
  applied where the contract is unchanged, with the queue slot still charged.

## 4. Transactions and atomic replacement

The [high-value list](2026-10-20-HIGH-VALUE-NEXT.md) names atomic replacement as
its first item, and the current `replace` mode tombstones a file before the new
bytes arrive. Four mechanisms get atomicity without a per-operation tax:

- **Publish, don't overwrite.** A writer builds the new value privately and
  swaps a pointer; readers keep the old version alive by reference. There is no
  empty-file window and no reader lock. This is the same discipline the runtime
  already uses to promote a message to shared on send.
- **Group commit.** One flush and one commit record per batch, with the batch
  atomic. A `write` returns after publish; durability is an explicit library
  operation, exactly as `fsync` is in UNIX.
- **Validate generations, not copies.** Where a transaction's read set must be
  checked, record `(resource, generation)` words and validate them in one
  message at commit. Conflicts become a refusal and a retry, and the
  no-conflict path carries no locks and no shadow copies.
- **Declared write sets.** Where the compiler can see a transaction's write set
  (the common transform), reserve the commit slot at admission and skip conflict
  detection entirely.

Keep the [reliability draft's](2026-10-06-FP-RISC-QOS-Reliability-Draft.md)
distinction: a protocol transaction is a conversation with a lifetime and an
outcome, not database atomicity. Nothing above adds isolation, rollback or
durability to the kernel.

Acceptance: interrupt at each boundary and observe the entire previous or the
entire new value; concurrent readers never see a partial replacement; a
committed batch costs one flush regardless of its size.

## 5. Gate it with invariants, not impressions

The FP-RISC benches measure the language. The OS contract needs its own:

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
  fairness all change. Move 12 is only safe where the caller already blocks and
  the queue slot is still logically charged.
- Do not make a declared bound advisory again to speed a test. Move 5 removes
  the per-operation check by making the bound provable; it does not weaken it.
- Do not claim a WCET from any of this until sleep/wake, flush and device
  completion have bounds. The audit's caution about `tau` in admissions still
  stands ([architecture audit](2026-09-29-QOS-ARCHITECTURE-AUDIT.md)).

## 7. Open questions

- Does the descriptor table belong to the runtime (one per process, visible to
  the loader's cleanup) or to `std/actor` (one per actor)? The runtime version
  gives `close`-on-death for free; the library version keeps the kernel smaller.
- Can the certificate be checked by the existing interval and bounds passes
  without a second analysis, or does it need a separate whole-program pass?
- Is a static-scheduler profile worth having for the fully declared case — a
  fixed actor set with run-to-completion dispatch and no backlog at all — or is
  Move 6 enough?
- For Move 7, is the receiver's ring the right allocation site, or should the
  sender own the slab and hand the whole slab over at publish (fewer partial
  writes, one ARC operation for a batch)?
