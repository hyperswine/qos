# Byte-string and CSS allocation deployment

Date: 2026-10-18. Deployment record for Raspberry Pi 4 and STAR64.

## Sources and build

- FP-RISC: `66b79999328387c66f253a5be522ba748bd48ebe`.
- QOS application source: `8eabf737b970a020a6577cf5629cfb35d80b71c0`.
- Disk updater: `cc2d706bf3e8eb8dc5f73ac0312ba46489ddaa5c`.
- Portable ABI 22, compiler code generation revision 48, six onboard apps:
  Clock, Logs, Browser, Disk, Terminal and Editor.

Builds use clean Git exports in a native AArch64 Ubuntu 24.04 container,
GHC 9.4.7 and GCC 13.3.0. STAR64 uses the Ubuntu RV64 Linux cross compiler
and target EGL/GLES libraries. The Pi also receives a matching native Editor
SDK. The STAR64 retains its existing compiler-service availability; this
deployment does not add a native RV64 Editor compiler SDK.

Main, the host, all six app archives and a fresh seed disk are rebuilt
together. The installed writable disk is updated separately after a clean
service stop. Kernel, firmware, boot/network policy, GPU stacks and service
configuration are retained. In particular, STAR64 keeps its matching vendor
PowerVR stack.

## Physical optimization checks

The new standalone test programs passed on both boards with one and four
workers: all 256 byte strings, zero `chr` allocations, invalid-input guards,
encodings, actor retention after sender death, and foreign-image unloading.

The CSS differential fixture produced the same 125,308 bytes on both
architectures and both worker counts. SHA-256:
`9119d98d67cab660377e5ac554473a30a10620a7866d326b907a600958e799cd`.

Both boards measured identical focused allocation costs:

| Operation | Allocated bytes |
| --- | ---: |
| 1,000 prefix comparisons | 0 |
| Join 256 class names | 349,648 |
| Emit 256 CSS rules | 394,224 |
| Typed-tree stylesheet | 1,581,488 |

These are focused test workloads, not a measured reduction in Main's idle
resident memory or an end-to-end UI performance comparison.

## Repeated disk updates

The Pi's writable disk had reached head 6,383 within a 7,168-page DATA
partition. Appending another complete bundle would exceed that boundary.
The explicit `--reclaim-app-history` update mode removes only superseded
onboard `QREC`/`QDEL` records. It retains every other record byte for byte,
including user history, tombstones and packed `QBLK` records, then appends
the complete current app bundle and index.

The updater validates both durable superblocks, committed record framing
and checksums, the standard app index and all resulting user values. It
refuses an active SWAP cursor or a nonzero compaction Merkle root in this
mode. Twenty updater checks passed, including repeated reclamation,
insufficient-space refusal and history preservation. The deployment's
independent verifier also compares the retained non-onboard record stream
and every latest user value.

Each installation retains a checked compressed rollback on its own board,
outside `/etc/init.d`. User disks and rollback contents stay on the boards.
Installation uses checksummed atomic file replacement after verified process
quiescence, followed by readiness and a 60-second service observation.

Atomic copies skip zero-filled chunks, truncate to the exact logical file
size, fsync, compare SHA-256 and rename. Space checks budget the largest
sequential staging allocation plus reserve. Mixed and trailing-zero copy
checks passed, as did all nine deployment-helper checks and seven health
sampler checks.

## Graphical preflight and limits

Both candidates are exercised with private RAM-backed seed disks, synthetic
keyboard input and real EGL GPU contexts, without injecting events into the
installed session. The workload opens Files, Logs, Browser, Clock, Disk,
Terminal and Editor, then checks normal quit and SIGTERM shutdown. Both
shutdowns must exit zero, without a timeout or forced kill. The GPU must be
V3D on Pi and PowerVR on STAR64.

The first Pi run exhausted the harness's 120-second deadline in its second
navigation cycle. It also emitted bounded app-worker stop warnings after
opening and immediately closing Editor. The repeat uses a 300-second bound,
the matching candidate compiler socket and 1.2 seconds for app jobs to settle
before closing the additional app tiles. Two navigation cycles and both
shutdown paths passed without those warnings. Several test conditions
changed, so this does not isolate their cause or establish a fix for rapid
close/reopen races. No production deadline policy changed in this deployment.

The Pi SDK passed the real daemon/assembler/linker protocol self-test both in
the builder and on the Pi: source checking, QAR2 plugin generation, stable
immutable publication, publication update, and rejection of invalid source.
The separate candidate compiler was stopped before the installed compiler
service was upgraded.

These are short acceptance runs. They do not establish long-term memory
stability or a human-observed HDMI/USB-input result. STAR64 had no attached
display; its graphical preflight used the actual PowerVR offscreen context.

## Deployment results

Both boards passed installation and final verification. Immutable installed
host/Main/seed hashes match the published source bundle, all six app images
loaded under ABI 22, normal writable-disk selection and input configuration were
restored, and the existing service/configuration files retain their original
hashes. The Pi's matching installed compiler completed a daemon round trip
and remained healthy alongside Main. Its installed graphics startup reports
`/dev/dri/card1 1024x600 (frame fullscreen)` with V3D, confirming that KMS
scanout resumed after the update.

| Board | SSH address | GPU | Installed RSS during 60 s (KiB) | Restarts |
| --- | --- | --- | ---: | ---: |
| Pi 4 | `192.168.0.233` | V3D | 71,368–72,072 | 0 |
| STAR64 | `192.168.0.215` | PowerVR B-Series | 57,304–58,508 | 0 |

Pi 4: writable log head 6383 → 2527; 25 old records validated and 25 onboard records reclaimed. Rollback: `/var/lib/qosp/deployment-allocation-20261018T050418Z/rollback.sh`.

STAR64: writable log head 1799 → 2319; 9 old records validated and 9 onboard records reclaimed. Rollback: `/var/lib/qosp/deployment-allocation-19700103T122503Z/rollback.sh`.

STAR64's rollback directory uses its unset wall clock (1970); identify this
deployment by the recorded revision and hashes rather than the directory's
date. The root archive, final verification and raw health samples are retained
on each board. No user disk was exported.

The [machine-readable record](evidence/2026-10-18-allocation-deployment.json)
contains complete immutable hashes, optimization ledgers, native SDK results,
preflight exits, service identities, short health observations and rollback
locations. Idle RSS is reported as an observation, not as a before/after
performance claim.
