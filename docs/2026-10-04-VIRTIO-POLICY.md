# Shared virtio initialization and block deadline decisions

Date: 2026-10-04. Kind: implementation record. First Phase 2 slice of
FP-RISC's `docs/2026-10-04-C-REDUCTION-PLAN.md`, using its `c-reduction-2`
compiler at `e8b8c74` (codegen 38). No runtime ABI or module pin change.

## What moved

`hal/virt/virtio.fpr` is a raw, allocation-free RV64 library over a U32 register
layout. Both the native block and network drivers call it for device discovery,
feature negotiation, split-queue address programming and DRIVER_OK. Calls use
plain C pointers/words and declared export signatures. Memory fences include
device I/O. The queue caller still clears and owns its backing memory.

The native kernel, QOS-side bare-metal builds and loaded native process build
all link the same unit. RV32 retains the original C routines; their source stays
as the fallback, so this is a reduction of active RV64 C policy rather than a
claim that every duplicated source line has been deleted.

`hal/virt/blockpolicy.fpr` makes the pure block deadline decision. It preserves
unsigned 64-bit elapsed arithmetic, wrap, the existing zero-clock behavior and
the park-count fallback without truncating clocks into tagged Ints. The three
call sites cover an orphan's reset deadline, a live owner's waiting budget and
the active request timeout. Deadline values remain caller-supplied C settings.

This slice preserves the existing device negotiation and fixed eight-slot
QEMU board discovery contract. It does not claim additional virtio features,
generalized queue geometries or stronger reset/negotiation semantics.

## Verification

- `python3 tools/virtio-check.py`: independent memory-backed C reference,
  executed under RV64 QEMU on one/two harts. Checks absent/wrong/unsupported
  devices, last-slot discovery, legacy/modern register results, queue-capacity
  refusal, high address words, and 729 full-word deadline boundary combinations.
- `tools/failure-injections-check.py --only netstall netorphan`: eight real
  network boots, legacy/modern and one/two harts; timeout, orphan completion,
  offline refusal and heartbeat progress passed. Production objects expose no
  injection entry points.
- Real `tests/diskstall.fpr`: four fresh disks, legacy/modern and one/two harts;
  timeout, successful reset and subsequent I/O, killed owner, failed reset and
  fast offline refusal passed. The regular disk-hardening runner now covers
  this same matrix; its full run passed, including the existing Portable
  stalled-worker, refusal and recovery leg.
- `tools/epproc-check.sh`: the normal native launcher and independently loaded
  process linked the new units and passed authorized display/clock, ungranted
  pin refusal and process-scoped storage round trip.
- Both C fallbacks compile to RV32 objects. This is compile evidence only.
- Module lock: all twelve pins remain resolvable. Python/shell syntax and Git
  whitespace checks passed.

The new differential leg is in `check-all.sh`. No complete check-all sweep,
hardware run or performance benchmark is claimed.

## Next boundary

Move block timeout/reset/offline state transitions and configurable budgets
above the driver, with one owner and an explicit request protocol. Preserve
the rule that killed/timed-out requests retain DMA backing until completion
or confirmed reset, including cancellation while reset is parked. C must keep
the cleanup hook and reservation mechanics until the replacement owns those
lifetimes. TCP/ARP actor migration, shared descriptor layouts, pins, IRQ routing
and runtime-service bootstrap remain later slices.

## Recovery policy follow-up (2026-10-04)

The pure `blockpolicy.waiting` transition table now selects park, reclaim a
completed orphan, reserve reset, or refuse an over-budget wait. Completion has
priority over timeout; an existing reset owner cannot be replaced. The raw
`resetStep` function decides confirmed status versus polling budget exhaustion.
C interprets these commands with the existing atomics and DMA operations.
Deadline values and polling configuration remain C settings, not live policy.

The reset path had no cancellation cleanup. Killing an actor parked while
resetting could leave orphan state 2 and the busy flag set forever; later
requests waited three deadlines rather than receiving immediate offline refusal.
A reset owner now registers a cleanup before it can park. On cancellation it
publishes offline before clearing orphan state and retains busy/DMA backing.
It does not release or reuse a potentially active or partially rebuilt queue.
Successful reset clears the hook before publishing recovered ownership.

The memory-backed differential additionally checks all 24 waiting decisions
and 256 reset-step combinations. `tests/diskresetcancel.fpr` is run before and
after the reset-status write, with each boundary on virtio v1/v2 and one/two
harts. All eight boots prove killed-owner failure, fast later refusal and
retained offline/busy state. Removing only the reset cleanup in a temporary
control build makes the same phase-1 fixture report `reserved=False fast=False
FAILED`; the log is `/tmp/qos-c2-reset-negative/negative.log`.

The full disk-hardening runner passed Portable, four normal native recovery
boots and these eight cancellation boots. Raw differentials passed one/two
harts. RV32 fallback compilation and production-object absence of test entry
points were also checked. No full repository sweep or hardware run is claimed.

## Configurable budgets and block protocol (2026-10-04)

`std/block.fpr` is an opt-in native service. `serve admin dev` starts one
serial request loop, with 64 mailbox slots **per sender channel**. `call`
uses `std/actor` correlation and returns `Result Reply String`:

| Request | Successful reply |
| --- | --- |
| `Capacity` | `Pages n` (4096-byte pages) |
| `Read page` | `Page bytes` (4096 bytes) |
| `Write page bytes` | `Written n` (accepted bytes, zero-padded on disk) |
| `GetBudget` | `Budget (version, deadlineUs, resetProbes, waitFactor)` |
| `Configure (expectedVersion, deadlineUs, resetProbes, waitFactor)` | `Budget` with the incremented version |

The request deadline is 1..60,000,000 microseconds, the reset budget is
1..100,000 status probes, and the waiter allowance is 1..64 request deadlines.
RV64 admission bounds live in raw `blockpolicy.budgetValid`; RV32 retains C
validation. Polling remains a mechanism setting: 200us for requests/waiters,
100us between reset probes. Defaults remain 5s, 1000 probes and factor 3;
`BLK_DEADLINE_TICKS` still overrides the initial deadline in test builds.
There is no persistence across reboot and no online restart command.

C's `blkBudgetSet` publishes a versioned configuration only while it can
reserve an idle queue. Invalid, stale, busy (including orphan/reset ownership)
and offline updates are refused without changing the version or fields.
Atomic 32-bit cells and a sequence snapshot prevent torn configuration reads
on both word sizes. A DMA owner snapshots deadline/reset budget on acquisition;
an orphan keeps that budget through recovery. A waiter snapshots its own wait
allowance when it begins waiting. Configuration never parks or allocates while
holding the queue reservation. `blkBudgetGet` allocates its tuple only after
taking the snapshot, without owning DMA storage.

The service rejects out-of-range pages and oversized writes before invoking
HAL I/O. Each capacity/read/write is executed by one short-lived worker. A HAL
fail-stop becomes `Err "block device: dead actor"`, while the service remains
available for budget queries and further requests. Invalid page, size, policy,
stale-version, busy, offline and mailbox-full conditions have distinct errors.
Returned device errors do not assert that a timed-out write never reached disk.
Queued requests have no additional queue-age deadline: their HAL wait/transfer
budgets begin when the worker runs.

The creator's actor ID is checked against the Configure request's return actor.
This is cooperative authority within a trusted image: a forged envelope or a
raw HAL call can bypass it. Process/namespace grants remain a separate boundary.
A client that dies after admission does not cancel the accepted write; the
worker finishes or times out, and replies to dead clients are discarded.
There is no transaction rollback, flush/durability guarantee, explicit cancel
request, service stop/drain protocol or global mailbox memory bound.

This is a protocol and configuration slice, not the completed Phase 2 move.
Qlog/filesystems still call the legacy block primitives; the system bootstrap
has not installed a unique block service or a namespace endpoint. C still
owns descriptors, queue atomics, cleanup registration, reset effects and offline
publication. Routing legacy users through one service and moving ownership
transitions above the driver remain follow-ups.

Verification for this slice:

- `tools/block-service-check.py` passed four real disk boots: virtio v1/v2,
  one/two harts. The fixture checks exact invalid/stale/authority/page/size
  errors, version preservation, active/orphan configuration refusal, page
  round trip, a measured 100ms timeout instead of the 300ms initial deadline,
  service survival, per-sender mailbox overload and stale-reply draining,
  caller death after DMA admission, recovery, configured reset-probe exhaustion
  (20 probes recovers after one delayed status; one probe takes it offline),
  later fast refusal and live budget queries while offline.
- The full `tools/disk-harden-check.py` passed its Portable leg, four normal
  native boots and eight reset-owner cancellation boots. Both held-reset
  boundaries additionally refuse reconfiguration and make a competing waiter
  exhaust the configured one-deadline/100ms allowance rather than 300ms.
  Cancellation still retains DMA storage and later callers are refused fast.
- `tools/virtio-check.py` passed one/two harts, adding 125 admission endpoint
  and out-of-range combinations across the raw ABI.
- `tools/epproc-check.sh` passed the normal launcher/loaded process storage
  round trip with the extended raw unit. The new service itself is a native
  kernel-library test, not a process namespace service or Portable feature.
- Production RV64 and fallback RV32 block objects compile. The production
  object has no test hooks; RV32 has no unresolved atomic-library helper.
  Python/shell syntax and Git whitespace checks passed. The service leg is
  included in `check-all.sh`; a full check-all sweep and hardware run were
  not performed.

## Qlog and bootstrap routing (2026-10-04)

The shared protocol and serial request loop now live in `std/blockio.fpr`.
`std/block.fpr` composes that loop with native budget query/update callbacks.
Import `blockio` for request/reply constructors and clients, and `block` for the
native factory. Portable uses the same page protocol and explicitly returns
`Err "block: native budgets unsupported"` for its budget requests; it links no
virt budget primitives and retains the host disk tier's deadlines.

Qlog v3.0 (`f556a08d099fbe45`) takes an explicit `PageSource`: `direct device`
for standalone format/corruption tools, or `routed blockActor` for service I/O.
Every Qlog read, write and capacity path uses that adapter, including metadata,
append, bulk, replay, verification, compaction and swap. Pure page APIs require
this adapter now; the low-level callers in-tree were migrated. `actor device`
remains a compatibility composition that creates a private block service;
`actorWith (routed blockActor)` uses the system-owned service. `FS.serveBlock`
and `FS.startBlock` compose Files on an existing block owner; the latter waits
for Qlog initialization/index scan via a stats request and returns a Result.

On a routed page error Qlog logs the reason and kills itself. Its RPC clients
receive the existing storage-service dead-actor error. It cannot continue
with an old head/index after a possibly partial append. The block service
survives, and its request worker retains the DMA cleanup lifetime. Starting
another Qlog actor on the same service runs `ensure` and scans the committed
log again. Incoming storage requests are kept/copied before nested block calls,
so receiving block replies cannot invalidate a borrowed client payload.

Native System.qa creates one block actor before querying capacity or starting
Qlog, and hands that actor to Qlog. With multiple configured harts the block
actor, its page workers and Qlog stay on hart 1, which can serve storage while
hart 0 synchronously runs a loaded process. On a one-hart kernel they use hart 0.
The existing C storage syscall binding is published only after Qlog answers
its readiness request. Failed initialization leaves storage offline and the
launcher usable; failed boot-record replay/append no longer prints an online
boot count. Portable `qsys` and `services` composition likewise create a block
owner first and wait for storage readiness before advertising it or attaching
apps. Application Files/namespace/Rpc contracts remain unchanged.

Publication order was shared block protocol, Qlog major version, native
factory, then consumer pins and regenerated lock. `blockio.v1.0` is
`17e531c2046076a6`; native `block.v1.0` is `70a7bd3df3e2b6b7`. All 22 pins
resolve from the local store. The interface comparison needed exact trust
entries for previously shipped Qlog/Svc blobs, whose source paths were already
trusted; no blanket store trust was added.

Verification:

- `tools/qlog-routing-check.py`: two Portable runs and 18 real native boots.
  Native kernels are separately compiled with `HARTS=1/2` to match QEMU's
  `-smp`, rather than pinning work to an absent configured hart. Across virtio
  v1/v2 the tests prove a failed append after pending metadata AND its header
  land (checked on disk), storage-actor death, block-service survival, rollback
  and restart without the uncommitted value, later append/replay/hash checks,
  and fast propagation of block-service death. The actual System.qa boots
  twice per disk with increasing persisted counters, stays offline on a
  stalled first metadata read, and boots without a disk. Both Portable runs
  exercise readiness, routed page I/O and native-budget refusal.
- Full disk hardening passes Portable startup failure with a surviving block
  service, four native request/recovery boots and eight held-reset cancellation
  boots. The existing four block-budget/protocol boots also pass.
- `tools/qsys-check.sh` passes two Portable boots with plugin reads and
  increasing persistent notes. `tools/epproc-check.sh` passes actual native
  process namespace/storage access. `tools/plugimports-check.sh` passes ABI
  refusal and corrupt-archive checks through the updated direct adapter.
- Qdisk and Qdisk2 both pass two Portable boots, including bulk, deliberate
  corruption/healing, compaction, swap wrap, full-log refusal and torn recovery.
  RV32 compilation, production absence of injection hooks, lock, syntax and
  whitespace checks are checked separately. No full check-all sweep,
  hardware run or performance claim is made.

Remaining boundary: no automatic Qlog restart or rebinding after a later
failure, no block namespace endpoint/cancel/drain protocol, and no enforcement
of a process-wide singleton against explicit standalone factories/raw callers.
C still owns DMA/queue reservation, reset effects, cancellation cleanup and
physical offline publication. Those ownership transitions are the next
migration, beyond this routing checkpoint.

## Stable Files owner and Qlog recovery (2026-10-05)

`std/fs` v1.0 (`42407f97b02f451f`) adds a stable Files RPC actor in
`startBlock` and `startBlockOn`. Native System.qa, Portable qsys and the
Portable services composition publish that owner after its first Qlog
initialization/index scan succeeds. Native binds the process storage syscall
once to this stable address. Namespace clients also retain the same address;
replacing Qlog needs no C pointer update or client reconnection.

The owner serializes requests and keeps their payload before nested receives.
Qlog's transport failure returns `Err "storage service: dead actor"` to the
original caller. The owner never replays that request: its mutation may have
committed before a lost reply. Before the next request, it creates a replacement
on the same storage hart and block service, waits for Qlog's pending-write
rollback/index scan, then forwards the new request. Ordinary Qlog operation
Errors preserve the current interpreter. A failed replacement readiness check
latches the owner offline; later requests return Errors immediately without
spawning more interpreters. Failed initial readiness kills the unpublished
owner and leaves bootstrap storage offline. Recovery is demand-driven, with
one readiness attempt per failure, rather than a background crash loop.

`serveBlock` and `serve device` retain the explicit standalone, unsupervised
factories. There is still no cancel/drain/stop protocol, no child cleanup when
an external caller kills the Files owner, and no administrative command to
bring a physically offline disk back online. The Files status endpoint still
reports whether an owner was published; operation Results report later
unavailability. C retains DMA reservation, atomics/fences, reset effects and
cancellation cleanup. Moving those ownership decisions behind an FP-RISC
command/effect boundary is the next checkpoint; TCP/ARP and the other dated
plan items remain open.

Validation: `tools/qlog-routing-check.py` covers two Portable runs and 24
native boots. Four new virtio v1/v2, matching one/two-hart fixtures interrupt
an append, recover through the same Files handle, prove the failed append was
not replayed, append/replay/verify again, then inject unconfirmed reset and
prove latched offline refusal with DMA backing reserved. Two additional
loaded-process boots bind the real storage syscall once, interrupt its append,
recover/replay through that unchanged binding, preserve unrelated mailbox
messages and reclaim process images. The existing routing, persistent boot,
failed initialization and no-disk matrix remains covered. Portable qsys's
two plugin/persistence boots and the complete disk-hardening suite (including
eight reset-owner cancellation boots) pass. No full repository sweep or
hardware verification is claimed.

## Atomic ownership with pure recovery policy (2026-10-05)

RV64 now takes ownership transitions from the allocation-free
`hal/virt/blockpolicy.fpr` `ownership` table. `blk.c` replaces independent
busy/orphan/offline flags with one atomic 32-bit ownership word. Idle, held,
orphan, reclaiming, resetting and offline are explicit states. Idle-to-held
CAS admits a request or non-parking budget update; a completed request releases
held ownership, while a timeout or owner cancellation produces an orphan.
Only a successful orphan claim grants completion acknowledgement or reset
work. Reclaiming and resetting retain the DMA reservation until acknowledgement
or confirmed reset plus queue reinitialization finishes. Failed/cancelled
recovery atomically publishes offline, which has no outgoing transition.
Invalid events preserve ownership; an invalid state value is quarantined.

The waiting table now consumes these ownership states. After claiming an
orphan, the driver rereads used-ring completion and deadline facts under its
exclusive reservation. The pure `claimStep` table decides acknowledgement,
reset, or return to orphan. This closes an observation-before-CAS race: another
waiter could reclaim an earlier completed orphan and abandon a new incomplete
request before the stale waiter wins its CAS. Its old completion observation
must never free the newer request's DMA. A retry retains backing and performs
no device reset or queue publication. Completion continues to win over reset.

The recovery cleanup hook now covers both reset and completion acknowledgement.
Cancellation in either claimed state leaves storage offline and reserved;
waiters retain their finite configured allowance, and budget configuration
refuses recovering/offline states. Actor death notification can precede
cleanup execution; the cancellation fixture checks the later refused request
and completed offline publication, rather than treating notification alone as
cleanup completion. The offline diagnostic now names unfinished recovery,
covering acknowledgement cancellation as well as failed reset.

C remains the effect interpreter: atomic ownership publication, fences,
cleanup registration, MMIO reset/status polling, queue acknowledgement and
DMA memory. RV32 retains C decision fallbacks and 32-bit atomic ownership.
This moves the ownership/recovery decisions, not the hardware mechanisms or
the reset polling loop. No block namespace/cancel/drain protocol, physical
online restart command, singleton enforcement, TCP/ARP migration or hardware
verification is added here.

Validation:
- `tools/virtio-check.py`: two RV64 raw ABI differentials against independent
  C references, including every ownership state/event, invalid inputs,
  post-claim fact combination, wait/reset/budget boundaries and register setup.
- `tools/block-ownership-check.py`: eight matching one/two-hart native boots
  across virtio v1/v2. Late completion is reclaimed without reset, cancellation
  during acknowledgement leaves DMA reserved/offline, and a controlled stale
  claim race resets the newer incomplete orphan rather than releasing it.
  A temporary raw policy mutation that skips completion revalidation is
  rejected by that race fixture. RV32/RV64 production objects compile, test
  hooks are absent, and RV32 needs neither raw RV64 policy symbols nor an
  atomic support library. RV32 execution is not claimed.
- The four native block-service budget/refusal/recovery boots and full disk
  hardening suite, including eight reset cancellation boots, pass. Their
  harnesses now build `HARTS` to match each QEMU `-smp` configuration.
- The Qlog routing suite passes its two Portable runs and 24 native boots,
  including stable Files recovery and actual loaded-process storage syscalls.

## Block namespace and cancellation/drain (2026-10-05)

`std/blockio` v2.0 (`1e7c2253c4828e32`) separates its admission actor from
one active disposable I/O worker and a completion relay. The relay turns
worker death into a Result without blocking the admission actor. At most 64
additional I/O requests are admitted to its FIFO; overflow is
`Err "block: queue full"`. This is a request-count bound, not a process-wide
mailbox/byte bound: mailboxes still have 64 slots per sender, and asynchronous
clients must reserve reply capacity and consume their responses. Capacity,
budget queries, status, cancellation and drain remain responsive during I/O.
Native budget updates still use the HAL's idle-only reservation check.

The added direct protocol is:

| Request | Contract |
| --- | --- |
| `Status` | `State mode queued active`; modes 0/1/2 mean open/draining/drained admission, not physical device health. |
| `Cancel id` | Cancel this caller's admitted request. `Cancelled True` means it was found; False means it was no longer pending or not yet admitted. |
| `CancelFor caller id` | The creator may cancel another caller's admitted request; other actors receive an administrator error. |
| `Drain` | Creator-only barrier: close admission, settle the active and admitted queued requests, then return `Drained`. Repeated drain after completion is idempotent. |

Queued cancellation removes the request and answers its original caller
`Err "block: request cancelled before I/O"`. Active cancellation kills the
worker and answers the original caller `Err "block: request cancelled (outcome
unknown)"` when the relay settles. A write can have reached the device before
cancellation: there is no rollback promise. The worker's DMA reservation and
cleanup continue to follow the HAL ownership policy. Only the active relay's
matching actor/id can finish a request; forged or obsolete completion messages
are ignored. Caller death alone still does not cancel accepted work.

`submit` returns a correlation id and `await` consumes that request's Result.
The existing synchronous `call` remains. `std/actor` drops replies with other
ids while awaiting a particular id: callers retaining both original and
control results must submit asynchronously and await the original before the
control reply. Cancellation acknowledgements confirm a protocol decision,
not physical cleanup completion. Drain settles protocol requests, does not
flush durability or promise hardware DMA quiescence after cancellation, and
keeps the actor alive for queries. New page I/O is refused after closure;
there is no resume or physical reprobe command.

`mods/blockep` v1.2 (`97237492694e7b1a`) exposes the system-owned service at
`/services/block`. Native System.qa, Portable qsys and services composition
register it without opening another Device or starting another block owner.
There are no default application grants to raw pages. The adapter keeps its
own client/mode-bound handles, copies borrowed messages before nested receives,
and reclaims turn temporaries with an actor boundary. A read-only handle
cannot write; another actor cannot use it; close removes it. Namespace grants
remain the process authorization gate, with the existing cooperative-image
trust limitation. Lifecycle administration uses the direct creator protocol,
not namespace URLs. Endpoint close does not cancel an outstanding page RPC.

| Endpoint | Value |
| --- | --- |
| `/services/block/capacity` | Read page count (`IInt`). |
| `/services/block/status` | Read admission mode, queued count and active flag (`IStr`). |
| `/services/block/budget` | Read native version/deadline/probes/factor text; Portable explicitly refuses native budgets. |
| `/services/block/pages/<decimal>` | Read exactly one page as bytes; write up to 4096 bytes and return accepted byte count. |

Page numbers are parsed digit by digit against reported capacity, before
multiplication, so malformed, signed, huge or out-of-range paths return Errors.
Raw page operations do not coordinate Qlog transactions or indexes; this
adapter does not enforce the filesystem's single-writer convention. Global
singleton enforcement, Files quiesce/stop coordination, resume/reprobe, and
TCP/ARP migration remain open. No hardware verification is claimed.

Publication follows the changed constructor identities: native `std/block`
v2.0 (`f6a778da43671433`), Qlog v4.0 (`5c94f0ce8d592d3d`), and compatible
Files v1.1 (`ef209d6518832a06`) all pin the new dependency chain. Old committed
versions remain intact. Exact prior Qlog/Files blobs were added to transitional
trust solely for their publication interface comparisons; blockio/blockep
compile with explicit schemes, without new blanket trust.

Validation: `tools/block-lifecycle-check.py` passes four Portable runs and
eight native virtio v1/v2 boots with matching one/two-hart kernels. It covers
responsive controls during stalled I/O, the global admitted queue bound,
queued/self/admin cancellation, original pre-I/O and unknown-outcome replies,
authority refusal, duplicate cancellation, drain admission closure and
idempotence, unchanged disk contents, and rejection of forged completion.
Namespace checks cover native budgets/Portable refusal, malformed/overflow
paths, full binary pages, payload/shape errors, app grants, handle mode/client
binding, closed handles and drained I/O refusal. Four native budget/recovery
boots, full disk hardening and reset-cancellation, the 24-boot Qlog routing and
loaded-process syscall matrix, Portable plugin persistence, and shared Files
prefix/compaction/refusal persistence checks also pass. This is focused
verification, not a full repository sweep.

## Files shutdown and RV64 TCP/ARP policy (2026-10-05)

`std/fs` v2.0 adds `quiesce me fs` and `shutdown me fs block` for the stable
owner created by `startBlock`/`startBlockOn`. The owner retains its creator
identity. Rpc tag 7 checks that claimed identity, serializes behind the current
Files operation, kills its Qlog child, and latches `storage offline: shutdown`.
It stays alive so namespace adapters and existing syscall bindings receive
explicit errors. It never rescans or restarts after quiesce. The shutdown helper
waits for that acknowledgement before the creator sends the block service's
administrator-only Drain. Repeated shutdown succeeds; a drain failure returns
`storage quiesced; drain failed: ...` and leaves Files quiesced. The standalone
`serve`/`serveBlock` compatibility actors do not implement this control.

The native System bootstrap now invokes this sequence when the startup app
returns, before its halt message. This is graceful logical settlement, without
an implicit compact, flush, durability promise, device reset, or resume. A
stalled current operation must finish/fail before quiesce can acknowledge.
Requests handled after the barrier are refused. Authentication remains the
existing cooperative message convention, not protection against a forged Rpc
caller field or arbitrary HAL access in the same image. `/services/files/status`
still indicates publication of a gateway; operation results report shutdown.

`hal/virt/netpolicy.fpr` moves RV64 Ethernet/ARP reply formats, IPv4/TCP parsing
and checksums, the four-connection lookup/allocation and sequence transitions,
binary receive buffering, fair poll selection, read limits and send segment
size into an allocation-free raw FP-RISC library. Typed byte and connection
layouts share a C ABI with asserted field offsets and stride. C retains NIC
queues, descriptor/fence/MMIO operations, static storage, TX ownership/deadlines,
and String allocation/copying. The public `netPoll`/`netRead`/`netWrite`/`netClose`
wire stays unchanged. Both the shared HAL makefile and the loaded-process build
script link the new unit. RV32 still compiles its original C transport.

Bounds precede variable header offsets. RV64 now drops malformed IPv4/TCP
headers, fragments, wrong ports/destinations, and corrupt checksums before
changing connection state. ARP requires an Ethernet/IPv4 request for our address.
Receive overflow acknowledges only stored bytes; FIN advances the sequence only
when its preceding payload fits, and advertised window follows available space.
An established peer's RST must match the next expected sequence. These are
correctness changes from the old unchecked parser and acknowledge-and-drop
buffer overflow behavior.

Fresh verification:

- `tools/files-shutdown-check.py`: two Portable and four native v1/v2 h1/h2
  creator/refusal/idempotence/persistence/drain-failure runs, plus four native
  shutdown-behind-timed-out-I/O runs. The latter retain the HAL reservation
  while reporting the logical block service drained; no recovery is triggered.
- `tools/net-policy-check.py`: RV32/RV64 production object ABI and absence of
  test hooks; two target-matched RV64 executions of packet, checksum, truncated
  header, fragment, table-full, sequence-wrap, binary payload, fair poll and
  backpressure fixtures. A checksum-blind temporary mutation is rejected.
- `tools/net-transport-check.py`: real QEMU slirp ARP/TCP and four simultaneous
  2573-byte binary echo peers, segmented both ways and closed with FIN, under
  virtio v1/v2 and one/two target-matched harts. The runner accommodates slirp's
  host listener accepting sockets before the guest handshake completes.
- `tools/failure-injections-check.py --only netstall netorphan`: eight native
  TX stall/orphan executions with deadlines, continuing heartbeat and offline
  refusals. Its builds now match each QEMU hart count. The console injection
  and production hook checks also pass.
- `tools/qlog-routing-check.py`: the routed Qlog/owner/bootstrap/process matrix,
  including two persistent System boots and the new successful shutdown log.
- `tools/qsys-check.sh` and `tools/files-service-check.py`: Portable plugin
  imports/persistent boots and Files prefix/compact/dead-owner refusals.

This completes Files-to-block shutdown coordination. TCP/ARP is a policy
migration checkpoint, not the complete Phase 2 actor design: connection storage
and polling still use the compatibility HAL composition. A frame-only
`rxFrame`/`txFrame`/`kick` interface, dedicated network actor and client migration
remain. The stack still has fixed 10.0.2.15:80, four peers, no retransmission,
congestion control, general TCP close/TIME_WAIT, DHCP or physical NIC evidence.
Physical block resume/reprobe and remaining Phase 2/3 items remain open.
