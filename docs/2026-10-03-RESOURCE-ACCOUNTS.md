# Resource accounts and a configurable currency for QOS

Date: 2026-10-03. Status: design draft, not an implemented API.

## Intent

Give each application and actor an explicit account for the resources it can
use. Make balances, consumption and policy visible through configuration, and
allow authorized policy changes while the system runs. Charge ordinary runtime
operations automatically: heap backing, stack growth, message storage, execution
and I/O. Programs should mostly remain ordinary FP-RISC clauses, guards and
vector pipelines, rather than contain manual accounting calls.

This extends [the memory-admission work](2026-10-03-MEMORY-ADMISSION.md) and
the [intended actor lifecycle](../../fprisc/docs/2026-10-02-ACTOR-MEMORY-LIFECYCLE.md).
The central owner grants resources at admission and exceptional growth; actors
carve and reuse their own admitted regions locally. Accounting must preserve
that low-traffic lifecycle.

## One account model, several resource units

A common currency could express the cost of different resources and influence
scheduling or growth decisions. Physical enforcement still requires separate
balances: bytes, execution time, queued messages and I/O throughput. Spare
compute credits cannot satisfy a memory reservation when no memory is available.

The proposed model has two layers:

1. Dimensioned accounts enforce capacity and rate limits.
2. Optional prices translate usage into common credits for reporting and policy.

Start with the first layer. A price mechanism should build on correct ownership
and counters, rather than become a prerequisite for admitting an actor.

| Resource | Enforcement unit | Charging event | Release or replenishment |
| --- | --- | --- | --- |
| Heap backing | Physical bytes reserved | Coarse grant or growth | Actual backing reclamation |
| Stack | Physical bytes reserved, plus a stack ceiling | Initial stack and new segments | Segment or actor reclamation |
| Communication storage | Backing bytes and queue slots | Storage grant and queue admission | Storage reclamation and dequeue respectively |
| Message rate | Sends per interval | Accepted send | Configured replenishment |
| Compute | Execution time per budget period | Execution consumed | Configured replenishment |
| I/O | Operations or bytes per interval | Operation admission and completion settlement | Configured replenishment |

Distinguish reservation, occupancy and cumulative consumption. A 4 MiB heap
grant reserves 4 MiB even when few objects occupy it. Repeated local allocation
can increase cumulative allocated bytes without requesting more backing. A
memory price may charge byte-time for holding that grant; releasing memory ends
future holding charges but does not refund time already consumed.

## Ownership and hierarchy

The system owns physical capacity and protects an explicit runtime-control
reserve. Applications receive accounts beneath it; actors receive grants from
their application. Child actors inherit account membership and may receive a
sub-budget. Spawning children cannot manufacture capacity or bypass application
limits. Ancestor counters aggregate descendant use, but each physical allocation
is counted once in the system total.

Every backing allocation needs a named owner and a release rule, including
entry captures, allocator and ARC metadata, message payloads, stacks and scratch
arenas. Shared runtime infrastructure needs an explicit shared account. Control
reserve use must remain visible and bounded, including retained actor records.

Memory can outlive its actor. Escaped or borrowed data keeps its backing lease
charged to the original application account until the final reference and borrow
window end. The account remains alive for that settlement even after actor exit.
Explicit ownership transfer, if supported, must reserve capacity in the receiving
account before releasing the source charge.

For messages, separate storage ownership from operation cost. A sender-created
payload is charged to its backing owner; receiver queue capacity is charged to
the receiver. Sharing one payload does not charge its physical backing again.
Copies create new allocations and charges. Queue-slot occupancy returns on
dequeue; payload backing may remain held afterward.

Shared services also need attribution. CPU or I/O performed on behalf of a
caller should consume a bounded delegated allowance or an explicit service
budget. A service must not accept an untrusted account identifier as authority
to spend another application's balance. Delegation needs to preserve both
authorization and exhaustion behavior.

## Admission and local execution

At spawn, declare initial heap, stack and communication reserves, growth
ceilings and the applicable rate policies. Admit the initial resources as one
transaction before publishing the actor. Refusal or cancellation returns every
reservation; a late service reply cannot leave a grant owned by a dead waiter.

Ordinary allocation within a grant updates local occupancy and high-water
counters. Resetting a slab retains the backing reservation. Stack and message
operations use locally admitted capacity where possible. Only exceptional
growth requests another grant from the owner, within both actor and ancestor
limits. Hard resource debits require exact enforcement; telemetry may be batched.
Do not add a service round trip to every allocation, function entry or send.

A growth request reserves quota and physical backing together. Neither an
account balance alone nor available buddy memory alone is sufficient. Pending
requests must participate in cancellation and configuration changes without
double charging or admitting against a superseded limit.

## Live configuration

Expose readable account state and authorized policy updates through QOS's
configuration/service model. The following is illustrative data, not supported
FP-RISC syntax or an existing endpoint contract:

```text
application:
  memoryBackingMax: 64 MiB
actorDefaults:
  heap: { initial: 4 MiB, max: 16 MiB }
  stack: { initial: 64 KiB, max: 512 KiB }
  messages: { backingMax: 2 MiB, queuedMax: 128 }
  sends: { budget: 1000, period: 1 s }
  compute: { budget: 5 ms, period: 20 ms }
```

Memory values refer to backing footprint; allocator alignment and buddy rounding
must be reflected in reservations. The application ceiling covers all attributed
memory, including infrastructure and descendants, not just actor heaps. A
maximum is permission to request growth, not a guarantee that growth will succeed.
Guaranteed capacity requires an explicit reservation policy. Compute budgets
need an explicit per-core or aggregate multi-hart interpretation before adoption.

Updates carry an expected configuration version and apply atomically, with a
reported effective version and enforcement boundary. An actor may adjust its
own policy only within authority delegated by its parent; increasing a hard
ceiling does not create physical capacity or override ancestor limits.

The initial policy should refuse a memory-limit decrease below outstanding
reservations. A later drain mode could accept the decrease, mark the account
overdrawn and prohibit growth until reservations fall. Neither mode frees live
objects. CPU/rate changes need documented replenishment semantics so repeated
updates cannot mint fresh credit. Price changes take effect at a declared epoch
without rewriting earlier consumption. Reservations pending across an update
must either remain covered by the new policy or be cancelled and rolled back.

Expose reserved and occupied bytes, peak occupancy, cumulative allocation,
pending grants, queued slots, execution consumed, rate balances, refusals and
throttling. Keep measurements in native units even when common-credit totals
are also displayed.

## Exhaustion and guarantees

Exhaustion is resource-specific. Failed spawn or optional growth should return
an explicit refusal where the API can do so. An ordinary allocation beyond an
actor's admitted hard capacity may retain actor-local fail-stop behavior. Sends
need a declared refusal or backpressure contract. CPU exhaustion parks an actor
until replenishment at an enforceable scheduling boundary. I/O admission needs
cancellation and settlement for already-started operations.

Accounting is not a WCET certificate. Current function-entry fuel is a
cooperative scheduling mechanism, not measured CPU time: vector kernels and
foreign operations can do substantial work between entries. Credible compute
limits need elapsed execution accounting and bounded scheduling boundaries,
including runtime kernels. Resource certification must separately connect
compiler bounds to target costs and the actual runtime footprint. Policy changes
must report when they invalidate a previously admitted guarantee.

Prices are policy inputs, not a proof of safety or isolation. Native cooperative
code still needs the runtime's existing trust assumptions; this design alone
does not make arbitrary native code unable to bypass accounting.

## Delivery order and evidence

1. Define account identity, hierarchy, ownership and exact counters. Instrument
   current admission, reclamation and retained control allocations.
2. Enforce composite memory admission across heap, stack, captures, metadata,
   scratch and communication backing. Route exceptional growth through accounts.
3. Add versioned live configuration with authorization, pending-request handling
   and explicit decrease semantics.
4. Add queue occupancy and message/I/O rate budgets, including service attribution.
5. Add measured execution budgets and bounded scheduling boundaries.
6. Experiment with common prices and adaptive policy using the established units.

Each stage needs failure-path evidence: denial at every reservation boundary,
cancellation before and after a reply, child-budget exhaustion, actor death with
escaped data, message copies/sharing, concurrent grants on multiple harts, and
policy updates racing with admission and reclamation. Assert conservation of
backing and quota, no publication after refusal, no negative or duplicated
balances, and successful later work after resources return. Also measure owner
requests to show that local allocation does not turn into accounting traffic.

The current implementation admits initial fixed-heap actors transactionally,
but the declared heap bytes exclude several other allocations. Stack growth,
messages and related paths still need complete accounting. This draft does not
claim whole-actor memory limits, live policy endpoints or compute quotas exist.

## Precedents and open decisions

[Linux cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)
provides a common hierarchy with distinct resource controllers.
[seL4 scheduling contexts](https://docs.sel4.systems/Tutorials/mcs) represent CPU
access through budgets and periods, and allow servers to execute on a caller's
scheduling context. These are precedents; the account and currency design above
is a QOS proposal, not a claim that QOS implements their semantics.

Before implementation, settle the memory grant layout and backing units, shared
control attribution, message ownership and backpressure contract, policy-update
boundary, multi-hart compute semantics, and whether capacity reservations promise
availability or only cap consumption. Common-credit pricing can remain optional
until those physical contracts hold.
