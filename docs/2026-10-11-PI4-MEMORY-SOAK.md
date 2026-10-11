# Pi 4 memory investigation and soak, 2026-10-11

The original Main driver and Graphics owner retained allocations on every
frame. Scoped reclamation removes that steady growth in the measured runs.
This is a follow-up to [the initial physical runtime checks](2026-10-11-PI4-RUNTIME-TESTS.md),
with both the failures and successful reruns preserved locally.

## Platform and isolation

Physical Raspberry Pi 4 Model B Rev 1.4, 8 GB, Buildroot/Linux 6.6.28-v8,
AArch64, Mesa 24.0.9 / V3D 4.2.14. The governor stayed at powersave, 600 MHz.
Executables were cross-built in the ARM64 Linux VM with the image's Buildroot
SDK, then run on the Pi with four workers and the real offscreen EGL backend.

The installed host was used without replacing it. Each test Main archive ran
with a separate copy of the disk under `/tmp`; the production Main disk and
service were not changed by these tests. Other activity administratively
restarted the production service and attached a display/keyboard during the
campaign. The isolated test processes remained independent. These are
concurrent endurance observations, not isolated performance benchmarks.

Private raw evidence is under `.qos/pi4/validation/`: `soak-30min-baseline`,
`soak-30min-scoped`, `soak-10min-final`, pool snapshots, original failures,
runner JSON and regression logs. Full smaps, executable/archive SHA-256,
temperature, CPU counters and V3D counters accompany the memory samples.
`tools/pi4/soak.py` reproduces observation; it does not start/stop an app or
claim application correctness from a stable PID alone.

## What grew

The initial observation retained the same production Main PID for 305.1
seconds. RSS rose from 182,896 to 193,972 KiB: **11,076 KiB**, about
**36.3 KiB/s** (128 MiB/hour if that rate persisted). Its intended 30-minute
run was interrupted by an external administrative restart, so it is a
five-minute baseline, not a completed soak.

The growth was in the FP-RISC application's anonymous arena. C heap and
global GPU buffer totals were approximately stable during that interval.
Read-only `/proc/PID/mem` snapshots, decoded against the matching ELF's
symbols and runtime structures, localized the retained allocation:

| Owner | Before reclamation | With reclamation |
|---|---:|---:|
| Main MVU driver | 31,884,928 allocated bytes / 436 slabs | about 25 KiB / one 64 KiB slab |
| Graphics service | 2,328,720 allocated bytes / 36 slabs | 320 bytes / one 64 KiB slab |

These are asynchronous allocator snapshots, not stop-the-world live-object
counts. They are supported by allocation-bound regressions and RSS samples.
Actor spawn count stayed at 1,939, stack misses at zero, and live ARC roots
stayed around 24–25 while idle. Opening a clock increased roots to 171 and
some namespace/lister allocations; subsequent snapshots stayed at that level.

## Repairs and contracts

FP-RISC `std/mvu` adds opt-in `runScoped` and `runLiveScoped`. The driver owns
a scratch arena, drops the current render reply after consuming it, and
transfers its live configuration/model/cache every 32 frames before resetting
the arena. Its caller's pool remains valid after return, including shutdown
handles. Scoped model/cache/environment state must have value semantics;
externally aliased mutable Vector storage is outside this runner's contract.
Existing `run` and `runLive` retain their previous allocation behavior.

QOS Guishell uses `runScoped`. Graphics transfers its persistent session and
backend closure before reclaiming each turn's temporary allocations. A
captured heap string in the backend survives the regression workload.

The fast four-worker Pi regression also exposed a scheduler race:
`actors: one context resumed on two harts`. A ready backlog entry could be
stolen while its wake was still travelling to the previous owner. Migration
now publishes ownership under the victim's backlog lock; admission checks
that ownership under the same lock and forwards a late wake. Stealing tests
the atomic running marker, and shipping captures one destination for both
the queue write and doorbell. The runtime's double-resume guard remains.
Ten consecutive physical Pi reproducer runs passed after the repair. This
is regression evidence rather than a proof of all possible interleavings.

The final FP-RISC revision is `b1a739ad602cbd237ae164ab9d2e3f2c89c34239`.

## Execution evidence

- The 20,000-frame scoped MVU regression checks bounded buddy allocation,
  preservation of caller-owned strings, and the returned model. It passed
  on the Mac with one/four workers, on the Pi with one worker, and ten times
  consecutively on the Pi with four workers and a 64 MiB heap cap.
- The Graphics regression rendered 100,000 frames. The old owner failed
  its 2 MiB retained-allocation bound at 4,864 KiB; the fixed owner passed
  with one and four Pi workers, preserving the backend's heap capture.
- Scoped live reload passed across two reclamation boundaries with one
  and four workers. The complete FP-RISC Base suite passed on the Mac.
- QOS smoke passed 16/16, including RV64 native link/execution and LiveView.
  Four RV64 TCP/ARP simulations passed across virtio v1/v2 and one/two harts.
  Those are QEMU results on the Mac, not native ARM OS execution.
- The real GUI regression passed in the Linux VM, including plugin pages,
  pointer protocol, two boots and graceful shutdown. It used the memory
  fixes before the scheduler repair; final scheduler hardware evidence is
  recorded separately above and below.

### Soak results

The 10-minute final archive completed 600.5 seconds of observation across
21 samples, with the same ready PID throughout. Smaps RSS rose from 160,396
to 160,712 KiB (**316 KiB**), then remained at that value for the final
four minutes. Its V3D submission counters continued advancing. At the
runner's scheduled 630-second stop, Files quiesced, block storage drained
and flushed, and the host reported `shutdown complete`. The runner recorded
exit 0, no signal exit, no timeout and no forced kill. Peak temperature was
69.140°C, with frequency at 600 MHz throughout.

The longer archive completed **1,800.5 seconds / 61 samples**, with the same
ready PID throughout. Sampled smaps RSS rose from 160,520 to 163,920 KiB
(**3,400 KiB**), including warmup and physical-input page activity, and
remained unchanged for the final five minutes. The idle portion before that
activity had already plateaued after a 256 KiB warmup. The final V3D counter
recorded 53,684 submissions on each of the bin/render queues. At the scheduled
1,830-second stop, storage drained/flushed and shutdown completed with exit 0,
no signal exit, timeout or forced kill. The runner's whole-run peak temperature
was 69.140°C, with frequency at 600 MHz throughout. No kernel OOM,
undervoltage or GPU reset/fault/timeout reports were observed.

| Observation | Duration | First/last sampled RSS | Outcome |
|---|---:|---:|---|
| Original Main | 305.1 s | 178.6 / 189.4 MiB | steady growth; external service restart interrupted observation |
| Memory-fixed Main | 1,800.5 s | 156.8 / 160.1 MiB | warmup/activity steps, plateau, clean stop |
| Final memory/scheduler Main | 600.5 s | 156.6 / 156.9 MiB | small warmup, plateau, clean stop |

The 30-minute archive has the memory fixes and the original scheduler;
the separate 10-minute archive includes the final scheduler repair as well.
Both use the same installed Portable host, with archive hashes below. Sampling
does not establish a bound on transient peaks or memory under arbitrary workloads.

| Artifact | SHA-256 |
|---|---|
| Portable host | `d900c6f334994b6c59826379be20aba1ccf2f3b4330db2efd95aab6061f0dc4d` |
| Baseline Main | `d8c9091f65d95a35f464ecbbddf92854dc6cc760b45f07383c1e5f6d87938566` |
| 30-minute memory-fixed Main | `bc1aac0431ce53cde40d4bfc862d266f6a2375d04bb894170624050ddb4befd1` |
| 10-minute final Main | `56b3dc2dd287f0991b102274c48eafa86091b0ae5e4e5d9268d9470104564d1d` |

## Remaining work

The Qlog owner retains roughly **116 MiB of allocated pool data after boot**
in all observed versions. Boot verification/index scans run in the same pool
as the persistent owner without reclamation. Its allocation stayed constant
in this workload. Separating scan/request scratch from the persistent index,
then testing repeated reads, writes, replay and compaction, is the next memory
target; idle-shell stability does not establish bounded storage workloads.

Global V3D counters already reported **29,770 BOs / 1,128,040 KiB** before
the isolated runs. Those totals include all GPU clients and are not process
RSS. One new offscreen context initially added about 21 BOs / 5,412 KiB.
Both isolated processes disappeared from the GPU client list on clean exit.
After both stops, global totals returned exactly to the pre-test baseline of
29,770 BOs / 1,128,040 KiB, leaving only the production service in the client
list. The large pre-existing allocation needs a separate fresh-boot and
repeated context-create/destroy investigation; these observations establish
cleanup of the new contexts, not the cause of that retained baseline.

An overnight run, interactive workload, repeated plugin open/close, storage
stress and repeated host restarts remain necessary. No production archive
or SD image was replaced with the memory/scheduler changes during this work.
These results apply to QOS Portable on Linux, not a native ARM QOS port.
