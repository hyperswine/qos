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
