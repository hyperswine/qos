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
