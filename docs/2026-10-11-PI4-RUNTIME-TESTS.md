# Physical Pi 4 runtime tests, 2026-10-11

The Pi is viable for FP-RISC application development through QOS Portable,
but these results do not establish an appliance ready for unattended use.
The tests found and fixed a real headless GPU crash that short startup and
screenshot checks had missed. Longer memory and endurance testing remains.

The subsequent [memory investigation and longer soaks](2026-10-11-PI4-MEMORY-SOAK.md)
localize and repair the per-frame growth discussed below. This report retains
the original campaign's results and deployment state.

## Platform and evidence

Raspberry Pi 4 Model B Rev 1.4, 8 GB RAM, original power supply, SD boot,
no HDMI display. Buildroot/Linux `6.6.28-v8`, AArch64, Mesa `24.0.9`,
V3D `4.2.14`, surfaceless EGL 1.4 / GLES 3.1.

QOS base commit `0ceb7d1` plus the working-tree changes, FP-RISC `1e4a6e4`.
Executables were built inside the ARM64 Linux VM using the image's Buildroot
toolchain, then executed on the physical Pi. Results below are hardware
results except the explicitly identified native simulations.

Private raw logs, JSON, framebuffer captures, memory samples and binary
hashes are under `.qos/pi4/validation/`. `run-1` preserves the initial
failures; `run-fixed` contains the corrected full suite. Network logs retain
both the startup-race failures and the subsequent readiness-based passes.
The reusable build, runner, test driver and supervisor probe are under
`tools/pi4/`.

## Results

- **111/111 runs passed** in the fixed core suite, including benchmark
  repetitions and the one/four-worker variants. This is an execution count,
  not 111 distinct specifications.
- FP-RISC: strings, bit-range checks, whole panic messages, blocked-actor
  reclamation, unread-mail reclamation, autodrop, fixed heap admission and
  child-only failures, sleep/wake behavior, concurrent digest tasks, wide
  and captured vectors, SIMD integer lanes, typed vectors, float filtering,
  sixteen floating-point reference checks, file operations and actor messaging.
- Heap growth: the large-heap probe completed with about 551 MiB peak RSS.
  A 64 MiB heap cap and a 64 MiB stack ceiling produced their named failures
  with exit 1; Linux and SSH remained available.
- QOS: routed block service, namespace grants, cancellation/drain deadlines,
  Files owner/grant refusals, graphics focus/lifetimes, shell model checks,
  and archive loading/calls through two onboard plugins.
- Real SD-backed Files replay and plugin state survived fresh host processes
  on one and four workers. Graceful signal-driven shutdown drained and flushed
  storage. An injected final flush error returned exit 1; an injected
  two-second stalled flush with a 250 ms deadline returned exit 124 about
  0.30–0.32 seconds after the stop request. Neither claimed clean completion.
- V3D GPU framebuffer readback passed. A focused test rendered **5,000
  offscreen frames**, then finished and captured the final image.
- Main completed **five minutes each with one and four workers**, followed
  by successful coordinated shutdown. Peak RSS was about 167–168 MiB;
  CPU time averaged about 0.13 and 0.19 of one core, respectively, during
  these idle-shell runs. Some additional test hosts ran concurrently during
  the soaks. Frame rate was not measured.
- **18/18 network runs passed**: owner lifecycle/start races and four
  simultaneous segmented 2,573-byte binary peers, on one and four workers,
  through Ethernet SSH, Wi-Fi SSH, and finally Wi-Fi with Ethernet down.
  The Wi-Fi-only check observed only WLAN routes before Ethernet restoration.
  Portable's listener deliberately binds loopback, so payloads traversed
  SSH forwarding; this does not establish a directly exposed LAN listener.
- The installed supervisor was tested with isolated disk/ownership paths:
  duplicate start preserved the child, two deliberate SIGKILL crashes
  recovered, a third exhausted the configured two-restart budget, an
  administrative restart reset the budget, and graceful stop completed.
- The shared network fixture also passed **four RV64 native simulations**:
  virtio v1/v2 and one/two harts. Those ran in QEMU on the Mac, not on the Pi.

## Failure found and repaired

The installed Main service had crashed four times and exhausted its restart
budget. The isolated shell reproduced `SIGSEGV addr=0x10` in roughly twenty
seconds, with both one and four workers.

Linux AArch64 fault reporting previously printed a placeholder `pc=0`.
Reporting the actual saved PC and link register resolved the fault to Mesa
`v3d_bo_map`, called by `v3d_cl_ensure_space_with_branch` with a null buffer.
This was outside the loaded FP-RISC image. There was no kernel OOM report.

Without a monitor, `gfx_present` performed neither swap nor scanout readback.
There was no submission boundary, so V3D kept extending the command list
until allocation failed. The EGL offscreen branch now calls `glFlush` at the
end of each frame; snapshots retain their explicit `glFinish`. The dedicated
5,000-frame regression crashed on the old host and passed on the fixed host,
followed by both successful Main soaks.

Initial network failures were a test-driver startup race: SSH forwarding
accepted local client sockets before the Pi listener was ready, and one
forwarded connection could fail late. Instrumentation showed only three
payload peers; changing timing moved the failure between worker counts.
The fixture now publishes readiness after starting the owner, and the
driver waits for it before connecting all four peers. All interface/worker
combinations subsequently passed. These failures are not attributed to the
QOS scheduler.

The first test driver also incorrectly expected Base to echo the returned
floating-point test summary and expected a diagnostic line on timeout.
Both output expectations were corrected and rerun; expected timeout status,
bounded completion and absence of a clean shutdown claim were retained.

## Performance

Median wall seconds of three runs, with exact output checks. The image boots
with `powersave` at 600 MHz. The second run temporarily selected `performance`
at the stock 1.5 GHz ceiling and restored the original governor afterwards.
Benchmarks ran before the shell soaks; no shell workload was active during
the fixed benchmark run. Other workers do not parallelize a scalar loop.

| Workload | 600 MHz, 1 worker | 1.5 GHz, 1 worker | 1.5 GHz, 4 workers |
|---|---:|---:|---:|
| Naive Fibonacci(35) | 0.909 | 0.362 | 0.362 |
| Pure FP-RISC SHA-256, 1 MiB | 3.289 | 1.397 | 1.398 |
| 1,000,000 actor request/reply round trips | 5.783 | 2.470 | 1.642 |
| Same, explicitly across workers | — | — | 1.641 |
| 10,000,000 floating-point orbit steps | 4.178 | 1.669 | 1.669 |
| 50 passes reading a 1,000,000-element vector | 4.059 | 1.637 | 1.638 |

The concurrent digest task probe took 3.140 seconds with one worker and
2.370 seconds with four. Pure SHA is allocation-heavy: the 1 MiB benchmark
peaked around 214 MiB RSS. This is not a native-library crypto throughput
claim. The process runner samples every 20 ms, so very short timings have
limited resolution.

Maximum observed temperature in the fixed core campaign was **60.861°C**.
Frequency samples stayed at 1.5 GHz during that campaign. Historical firmware
throttling flags were not collected.

## Running device and image

The production host, without test fault-injection flags, is now installed on
the Pi. The previous host is backed up as `/usr/bin/qosp.before-headless-flush`.
Main was administratively restarted after its earlier exhausted budget;
the installed binary matches the refreshed image's packaged host. Subsequent
checks found the same Main PID healthy at the restored 600 MHz setting,
with both network interfaces back up. Isolated test disks were removed after
collecting their results; the installed Main disk was preserved.

The private `.qos/pi4/sdcard-fixed.img` was rebuilt and checked: its root
partition matches the verified filesystem, which contains the fixed host,
tested Main archive and Wi-Fi fixes. Its SHA-256 is
`98048dbe67e89ca9c213d1189ad6b62c2462a5d7a9ff02f973ae878c387188e6`.
It contains provisioned Wi-Fi settings and remains local with mode 0600.
The card received the host update over SSH; it was not reflashed for this run.

## Remaining boundaries

These are QOS Portable-on-Linux results, not a native ARM OS port. No physical
power cuts, HDMI scanout, physical input device or audio-output checks were
performed. Shutdown fault injection and fresh-process replay establish those
contracts, not resistance to arbitrary SD-controller power loss.

The five-minute shell samples showed RSS rising by several MiB rather than
establishing a plateau. This may include allocator/driver residency; it is
not yet evidence of stable long-term memory use. An overnight soak with heap
and GPU allocation instrumentation is the next reliability test. An adaptive
CPU governor should also be evaluated before retaining the current 600 MHz
boot default for an interactive application.
