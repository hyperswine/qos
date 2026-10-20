# QOS validation with consuming workers

QOS is pinned to FP-RISC `4c16996364c38b8ef1a8a82500813225cf7e3436` (code generation revision 55).
The tested QOS source is `d340ecb53a45ddf2f95ad9c9a3aab6db7361c330`. The compiler commit's
source hashes match the exported Linux build sources and physical-test evidence.
The runtime ABI remains 22. All **302 dependency pins** resolve and `fpr.lock`
is current. The complete FP-RISC Base suite and **16/16 QOS smoke checks** passed.
The initial Linux container lacked its bare-metal RISC-V compiler and QEMU;
installing those prerequisites allowed all three virtual-machine checks to pass.

Both boards ran matched host, Main and six onboard-app bundles on private disks.
The tests injected keyboard events, opened Files, Logs, Browser, Clock, Disk,
Terminal and Editor, required the board GPU's EGL renderer, and verified normal
quit plus signal shutdown. Each test binary was checked against its local SHA-256.

| Board | GPU | Workload | Normal quit | Signal shutdown | Installed session |
|---|---|---|---|---|---|
| Pi 4 | V3D | 2 navigation cycles | exit 0 | exit 0 | PID 7660, restarts 0, unchanged |
| STAR64 | PowerVR | 1 navigation cycle | exit 0 | exit 0 | PID 32320, restarts 0, unchanged |

This is short scripted compatibility coverage, including offscreen GPU rendering.
It is not manual HDMI acceptance, an Editor compilation test, or a long-term
memory bound. Candidate bundles were not installed over the running sessions.
All task-created board test directories were removed after successful shutdown.
The Linux build container was stopped after testing.

The separate compiler probe reduced 10,000 helper updates from 20,000 to 10,000
allocation requests on each board. Seven-sample medians fell from 622.841 to
362.393 ms on Pi and 362.830 to 221.691 ms on STAR64. These allocation-instrumented
microbenchmarks are not an application-wide QOS speedup claim.

[Structured evidence](evidence/2026-10-20-consuming-workers-qos.json) includes the
exact compiler source hashes, bundle manifests, GPU log hashes, process state,
shutdown results and temporary-directory cleanup. Compiler safety tests and
scope are documented in FP-RISC's `docs/2026-10-20-CONSUMING-WORKERS.md`.
