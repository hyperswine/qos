# Private-worker compiler deployment to Pi and STAR64

Date: 2026-10-18. Kind: deployment and acceptance record.
QOS application source: `cd83f0a6022db591527d0bb685fc5db7b9da8637`.
FP-RISC: `2ce2f5a48f4490fdce0d641b32b97d364d0cb590`.
Portable ABI 22, code generation revision 49.

## Scope and build

QOS now pins the private scalar/two-field worker compiler. The host, Main,
Clock, Logs, Browser, Disk, Terminal, Editor and a fresh seed disk were rebuilt
from clean committed exports for Linux ARM64 and Linux RV64. The Pi also gets
a matching native Editor compiler SDK. STAR64 retains its existing compiler
service availability; this release does not add a native RV64 Editor SDK.

The build uses the existing native ARM64 Ubuntu 24.04 environment, GHC 9.4.7,
GCC 13.3 and RV64 cross GCC. The SDK is tested on the container's native
filesystem because the host-shared extraction path rejected its relative
toolchain symlink. This did not change the SDK archive.

The existing graphics, kernel, firmware, boot, networking and service settings
are retained. The writable application disk is updated after stopping Main,
with compressed board-local rollback, checksummed atomic replacements and
independent checks that non-onboard history and latest user values survive.
Superseded onboard-app history may be reclaimed by the checked updater.
User disk contents are not exported.

The emitted app assemblies select one private scalar `digitsOf` worker in an
Editor dependency on each architecture. They select no two-field workers in
these images. This is a compiler capability release; a general shell speedup
is not established by the synthetic worker benchmarks.

## Acceptance

The compiler worker suite passes again before publication. The dependency lock
validates all 245 pins; QOS smoke passes 16/16, including native/portable,
RISC-V QEMU, shell controls, storage and LiveView checks. Deployment-helper,
health-sampler and disk-updater suites pass 9, 7 and 20 tests respectively.

Each candidate uses a private RAM-backed seed disk, synthetic keyboard events
and a real GPU context to exercise navigation and onboard apps. Normal quit
and SIGTERM must both complete with zero exit status, without timeout or forced
kill. The Pi uses its matching private compiler socket during preflight.
The SDK protocol self-test checks source validation, QAR2 compilation,
immutable publication/update and invalid-source refusal, in Linux and on Pi.

Both boards passed installation, immutable-file verification, configuration
preservation and a 60-second installed-service observation with zero restarts.
The Pi's installed compiler completed its daemon round trip and stayed healthy.

| Board | GPU | RSS range (KiB) | Restarts |
|---|---|---:|---:|
| Pi 4 | V3D | 71,420–72,060 | 0 |
| STAR64 | PowerVR B-Series | 57,172–58,424 | 0 |

Pi 4: log head 2527 → 2527; 7 old records validated and 7 onboard records reclaimed. Rollback: `/var/lib/qosp/deployment-workers-20261018T093826Z/rollback.sh`.

STAR64: log head 2319 → 2319; 7 old records validated and 7 onboard records reclaimed. Rollback: `/var/lib/qosp/deployment-workers-19700103T170853Z/rollback.sh`.

STAR64 uses an unset wall clock, so its rollback directory may have a 1970
timestamp; identify it by the recorded revisions and hashes.

Private candidate files were removed after verification; rollback archives
and acceptance records remain on both boards.

These checks are automated acceptance and a short service observation. They
do not establish long-term memory bounds, physical USB keyboard behavior,
human-observed display quality or an end-to-end QOS speedup. The compiler's
synthetic worker measurements are recorded separately in FP-RISC's
`docs/2026-10-18-PRIVATE-WORKERS.md`.

The [JSON evidence](evidence/2026-10-18-workers-deployment.json) records source
revisions, immutable hashes, preflight exits, SDK results, disk-update summaries,
service identities and rollback paths. Raw installed-health samples and the
compressed rollback are retained on their respective boards.
