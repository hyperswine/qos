# Qlog memory and scratch arena repair, 2026-10-11

Qlog now reclaims boot verification, index scan and request temporaries while
preserving its page source and persistent index. This removes the roughly
116 MiB retained boot pool found in the [previous Pi investigation](2026-10-11-PI4-MEMORY-SOAK.md).
The block adapter still retains actor identities per I/O, so indefinite storage
workloads do not yet have bounded global memory use.

## Changes

Boot metadata handling, verification and index scans use scratch arenas.
Verification hashes each payload page in its own arena, retaining only the
integer hash state. Payload reads gather page slices and join once, replacing
successive concatenation of growing prefixes. The returned binary String is
copied out before scratch teardown.

Before Qlog serves its first request, it transfers the page source, head and
index through `std/actor.boundary`. Subsequent requests use adaptive `Tidy`
checkpoints with 1 MiB slack. Reclamation copies only persistent state; copying
the entire index on every read would make read cost depend on index size.
This requires the persistent state to retain its existing value semantics.
Stats tag 5 now appends `pool-bytes=...`, the owner's logical pool allocation,
so tests can distinguish Qlog retention from allocation elsewhere.

Asynchronous block I/O exposed an FP-RISC runtime bug: `Sys.arena` and
`Sys.loopWith` remembered the entering hart and restored that hart's pool
override after a thunk returned. An actor may park and resume on another hart
inside the thunk. Teardown could then corrupt a different actor's pool.
Both primitives now capture the stable actor-owned override slot before any
operation that can park, and restore that slot after migration.

The original two-worker durability run crashed with SIGSEGV at address
`0x1000`; the full durability rerun passed after the runtime repair. A dedicated
regression parks inside nested arenas and loopWith, preserves caller strings
and the loop's Vector, and requires observed migration on multiple workers.

## Validation

`tools/qlog-memory-check.py` seeds a checksummed 32 MiB Qlog v3 disk with a
1,048,593-byte binary record, including NULs and a partial final page, and a
packed record with duplicate URLs. Each process performs 48 large reads,
24 append/replay/delete cycles, four compactions, verification and a drained,
flushed shutdown. A second process checks the same disk's persisted stream.
One/four workers each run both boots with a 64 MiB global heap cap.

The test asserts boot buddy cost below 8 MiB and sampled Qlog pool allocation
below 4 MiB. It reports global allocation growth separately. These are sampled
owner checks, not a bound on transient peaks or arbitrary live index sizes.

- Local Portable: all four cases passed. The first case retained 1,984 KiB
  at boot, with Qlog samples of 113,648 / 38,544 / 508,256 / 45,872 / 43,792
  bytes across boot, reads, mutations, compaction and final reads.
- Physical Pi: all four cases passed, with no signal exit, timeout or forced
  kill. Both fresh processes preserved replay and completed drained, flushed
  shutdown. The first case had the same allocator samples as the local run.
- Portable durability passed: format/reopen, migration refusals, corrupt
  metadata and payloads, partial final pages, staged crash recovery,
  compaction, capacity refusal and all injected flush boundaries.
- QEMU RV64 routing and Files shutdown passed across virtio v1/v2 and one/two
  harts, including recovery, partial append, failed initialization and DMA
  remaining reserved behind failed I/O. These are native RV64 simulations,
  separate from Portable on the physical Pi.
- Nested arena migration passed locally on one/four workers and on the Pi
  with four workers, observing 81 migrations. The Pi run exited 0 in 0.269
  seconds with 2,944 KiB peak RSS.

The complete FP-RISC Base suite passed on the Mac, including the new migration
regression. Its first attempt was blocked by the sandbox's loopback-listener
restriction; the network-enabled rerun completed successfully.

| Physical Pi case | Runtime | Peak RSS |
|---|---:|---:|
| One worker, boot 1 | 215.0 s | 39,836 KiB |
| One worker, boot 2 | 213.5 s | 40,276 KiB |
| Four workers, boot 1 | 196.9 s | 41,284 KiB |
| Four workers, boot 2 | 162.2 s | 41,588 KiB |

These timings include verification, mutations, compaction and SD flushes under
concurrent appliance activity at 600 MHz; they are not read-throughput results.

## Physical Main observation

Platform: Pi 4 Model B Rev 1.4, 8 GB, Buildroot/Linux 6.6.28-v8, AArch64,
Mesa 24.0.9 / V3D 4.2.14. Powersave remained at 600 MHz. The new Main archive
uses the existing installed host, a separate disk copy and offscreen EGL.
DRM is disabled and the keyboard source is an empty file; the input backend
still opens `/dev/input/mice`. No synthetic input was sent. The production
service and disk were not replaced or restarted by these tests. These are
concurrent endurance observations, not isolated performance benchmarks.

A read-only `/proc/PID/mem` snapshot decoded using the matching ELF symbols
and runtime structures identifies Qlog's `actorWith` owner at **1,792 allocated
bytes / one 64 KiB slab**, versus 121,288,816 allocated bytes before this work.
The snapshot is asynchronous, supported by the explicit pool regression.
Main's sampled RSS was 38,536 KiB initially and 38,624 KiB after warmup,
compared with roughly 160,400 KiB in the previous fixed Main observation.

The final observation completed **600.5 seconds / 21 samples** with the same
ready PID. RSS increased by **88 KiB**, then remained at 38,624 KiB after the
first minute. V3D bin/render submissions continued advancing. At the scheduled
630-second stop, Files quiesced, block storage drained and flushed, and the host
reported `shutdown complete`. The runner recorded exit 0, no signal exit,
timeout or forced kill, with peak temperature 64.757°C at 600 MHz throughout.

Global GPU totals stayed at 29,794 BOs / 1,135,776 KiB during observation and
fell to 29,774 / 1,130,368 KiB after shutdown. That is four BOs / 2,328 KiB
above the older pre-test baseline. Concurrent production GPU use prevents
attributing that difference to this context. The large pre-existing global
allocation remains a separate investigation.

Raw evidence is private under `.qos/pi4/validation/qlog-memory`: local and
physical case logs, runner JSON, the original crash, durability/routing/shutdown
logs, allocator snapshots, matching symbols, smaps, GPU counters and hashes.
The AArch64 application archives were built with FP-RISC's freestanding
Clang/lld path in the ARM64 Linux VM; the Base migration executable used the
Pi image's Buildroot SDK. No native ARM QOS kernel was tested.

| Artifact | SHA-256 |
|---|---|
| Installed Portable host | `d900c6f334994b6c59826379be20aba1ccf2f3b4330db2efd95aab6061f0dc4d` |
| Main with Qlog/arena fixes | `eb7d39b7d7717cca3fd4289ce550efc5850fb13c81751e460895ea008a0861ad` |
| Pi Qlog regression archive | `678e75333cecc26fb5c68e8cbded56a901df842bd5f76e0aa81df795f5d454c3` |
| Pi arena migration executable | `e7cffa29af85bf9f01ef33d53f4d6fb66984656c5ef04ffe59664a6937392bb9` |

## Remaining block I/O growth

The first Qlog stress case still retains **25,472 KiB globally**, even though
Qlog's own final sample is only 43,792 bytes. Across the local cases the global
increase was 25,472–26,304 KiB. `std/blockio.start`
creates a worker and a completion relay for each I/O. Their stacks and slabs
are reclaimed, but FP-RISC keeps actor control blocks immortal so a late send
to a dead actor cannot target a reused identity. An AArch64 control block is
656 bytes. Forty reads of 257 payload pages create about 13 MiB of this ledger,
matching the measured 13,376 KiB growth after those reads.

The next repair should reuse block workers and completion relays while
preserving cancellation, drain, worker-death detection and refusal behavior.
Recycling actor addresses alone would break identity safety. Qlog owner
reclamation does not solve that ledger, bound a growing live index, establish
physical power-loss durability, or explain the pre-existing global GPU BO
baseline. The installed production archive and SD image still need a separate
deployment after validation.

## Stored interfaces

The final modules are Qlog v7.0 `3c2ad30ff14444d6`, Files v3.2
`aeb97cb13f0aff84`, and lifecycle v3.0 `f95ec7dce656d2bb`. The dependency pins
are refreshed through Main, with `fpr.lock` resolving all 53 pins. Earlier
immutable versions minted during implementation remain in the store.
QOS pins FP-RISC `4f621a38ac02588a72ec1b6a2fa57a2a0b25ff4f`, which also
contains the concurrently published Tang Nano changes.
