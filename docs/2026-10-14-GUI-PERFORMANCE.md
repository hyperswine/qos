# Main GUI timing and memory - 2026-10-14

This slice adds opt-in timing evidence and fixes retained receive roots found
by a longer Main workload. Application policy remains FP-RISC MVU with named
functions and data messages. The installed Pi application and CPU policy were
not replaced.

## Diagnostic composition

`tests/mainprofile.fpr` owns `(shellModel, inputStamp)`. Its named update
function delegates to the shell update and records a monotonic timestamp and
sequence for keyboard input. Its view delegates to the shell view and records
which updated model it used. `Shell.runProgram` runs that ordinary MVU program
through the normal boot, owned message port, deadlines and shutdown. Normal
Main still builds its original MVU program; it has no diagnostic model fields
or timing output. No lifecycle hooks or callback registry were added.

`FPR_GFX_PROFILE=1` enables native poll, draw and submission timestamps in
`hal/unix/gfx.c`. `FPR_GFX_PROFILE_FINISH=1` additionally waits for GPU completion
and is meaningful only with profiling enabled. It must be a separate run:
forcing `glFinish` changes the workload. `FPR_GFX_TRACE` remains available for
human-readable draw diagnostics. Profiling is disabled by default.

`tools/gui-profile-report.py` matches a native key press to its FP update,
then to the first frame carrying that model's sequence. An older in-flight
frame cannot satisfy the input measurement. Inputs coalesced by a drain batch,
and quit inputs without a subsequent frame, are listed separately. Native
stderr mirrors are counted once. Retained unchanged pixels do not claim a new
GPU submission. Missing identity or reversed/incomplete timestamps fail the
report rather than producing plausible latency numbers.

The measured boundary starts when the native poll returns an event. It excludes
kernel/device waiting before polling, SSH injection delay, and physical display
scanout. Draw, view and frame-interval numbers are wall-clock durations, not CPU
instruction time. Offscreen submission does not prove GPU completion. Neither
submission nor a forced GPU finish is device-to-photon latency.

## CPU policy and isolated driver

`tools/pi4/gui-profile.py` runs a matching bundle locally or on the Pi. It
exercises home navigation, a cached Files pane and the Browser app, then quits
through normal storage drain. The Pi runner bounds the application to 90
seconds and records actual CPU frequency, temperature, CPU time and peak RSS.
It uses a private RAM-backed disk and input FIFO. Installed service identity
must remain unchanged.

`tools/pi4/cpu-policy-run.sh` owns an exclusive temporary policy lock, saves
all cpufreq policies, selects `keep`, `powersave` or `performance`, and restores
them after its bounded command finishes. A disconnected SSH client does not
cancel the remote deadline/restore sequence. INT/TERM interrupting the guard's
wait cannot restore the policy while the bounded command is still running;
it waits for completion, restores, then returns the interruption status. A
hard kill of the guard or loss of board power cannot execute a restore trap.
This is a benchmark control, not a persisted boot policy.

Build a fresh matching bundle inside the ARM64 Linux SDK checkout:

```sh
export FPRISC_ROOT=/path/to/exact/fprisc
export TARGET_CC=/path/to/buildroot/host/bin/aarch64-buildroot-linux-gnu-gcc
out=/path/to/fresh/gui-bundle
mkdir -p "$out"
for name in clock logs browser disk; do
  make -s plugin-qa-a64 PROG=apps/$name.fpr PLUG_OUT=$out/$name.qa BUILD=$out/build-$name
done
python3 tools/mkdisk.py "$out/Main.disk" 32 "$out/clock.qa" "$out/logs.qa" "$out/browser.qa" "$out/disk.qa"
for name in mainprofile mainmemory appsessionmemory; do
  make -s qos-app-a64 PROG=tests/$name.fpr QA_OUT=$out/$name.qa BUILD=$out/build-$name
done
make -s -C qos portable-es QOSP_ES_OUT=$out/qosp-es \
  FPRBUILD_EXTRA="--cc $TARGET_CC" SND_FLAGS=-DQOSP_SND_ALSA SND_LIBS=-lasound
"$TARGET_CC" -O2 tools/pi4/runner.c -o "$out/runner"
cp tools/pi4/cpu-policy-run.sh "$out/"
```

Use the Pi image's Buildroot compiler for `TARGET_CC`; the archives and host
must share the exact SDK revision. Transfer into a new private Pi directory.
For a local desktop run, provide `qosp-gl`, `mainprofile.qa` and a matching
`Main.disk` in `--bundle`; omit the SSH arguments and use `--governor keep`.

```sh
python3 tools/pi4/gui-profile.py \
  --host 192.168.0.233 --host-key-alias 192.168.0.232 \
  --identity ~/.ssh/id_ed25519 --known-hosts .qos/pi4/known_hosts \
  --bundle /tmp/qos-gui-profile --governor performance \
  --output .qos/validation/gui-performance/performance
```

Run policies serially. Use a fresh output directory each time. `--finish` is
a separate GPU completion diagnostic; `--retain-ui` can evaluate the existing
retained-pixel mechanism. CPU policy and installed service before/after,
artifact hashes, raw logs and distributions are saved with every successful
remote run. Failed remote candidates still have the bounded runner; inspect
its private log and policy restoration before starting another run.

## Receive-root retention found and fixed

The initial 64 MiB arena run used the previous responsive slice's matching
host and app archives. Five samples grew from 76 to 311 live roots and from
49,088 to 59,584 KiB reserved arena memory. RSS grew from 55,948 to 66,960 KiB.
At 266.90 seconds the process exhausted its message slab and exited with a
panic. The installed GUI remained healthy. This exposed a lifetime failure
that the earlier 72-87 second acceptance runs could not establish.

`appclient`, `appsession`, `appjobs` and the pane read worker unpacked received values through
Result/custom Inbox wrappers without releasing the original received roots.
The app-session adapter also returned borrowed worker/bootstrap/self-result
payloads in new constructors. They now copy the needed data with `keep`, drop
the original received root, and pass owned turn data onward. Their existing
`Sys.loop` boundaries reclaim those copies after each turn. State, deadlines,
protocols and failure behavior remain unchanged.

An intermediate run after fixing the app boundaries retained roughly three
roots per navigation cycle while RSS was much steadier. This isolated the
same wrapper pattern in `panejobs.readStep`; it was fixed before final
acceptance. The intermediate candidate was deliberately stopped through
SIGTERM and drained storage cleanly. Its evidence is retained separately.

`tests/appsessionmemory.fpr` warms the actual Clock session, owner and job
worker, then performs 3,000 events, owner calls and worker reads, including
self-result forwarding and pane reads. It requires at most eight additional roots and less
than 2 MiB additional reserved memory. The contract fails against the previous
source and passes with the fix on the host and physical Pi with one/four
workers and a 64 MiB arena. It is included in the standard GUI and Pi suites.

`main-soak.py` now preserves log/runner/error evidence on failure and opens its
keyboard FIFO read/write, avoiding a blocked FIFO open after the app dies.
For opt-in allocator sampling, the soak discards the first three samples as
warmup, then bounds subsequent root growth to eight and reserved-memory growth
to 4 MiB. Fewer than two post-warmup samples cannot verify that bound. RSS
continues to have its independent growth limit.

Main plus all four archives need rebuilding together to install the lifetime
fix; rebuilding the shell cannot repair app copies already stored on disk.

## Physical Pi timing baseline

QOS base `b137f26a60e0264b4d3a0b46f6ecd10b80fc1fdb`, with this slice applied;
FP-RISC pin `aee3e962c8c3f2d6d4967a35e035856258de5ce6` unchanged.
Physical Pi 4, EGL/V3D offscreen 1280x720, four workers, 128 MiB application
arena, normal lighting, no retained-pixel optimization, diagnostic logging on.
One run per mode; 85 correlated inputs per run. These are initial baselines,
not repeated controlled statistical comparisons or physical scanout results.
The installed supervisor stayed at PID 279, restart count zero. Its GUI kept
running, so these runs isolate application state, not all CPU/GPU contention.

| Mode | Actual CPU | Input poll to submission p50/p95 | FP view p95 | Native draw p95 | Frame interval p95 |
| --- | --- | --- | --- | --- | --- |
| powersave | 600 MHz | 18.21 / 23.63 ms | 15.27 ms | 2.82 ms | 40.56 ms |
| performance | 1500 MHz | 9.34 / 11.69 ms | 5.22 ms | 1.00 ms | 35.95 ms |

A separate synchronized performance run measured input poll to GPU completion
p50 19.73 ms, p95 25.68 ms; GPU wait p95 15.43 ms. It exited cleanly at 51.98
seconds. Asynchronous powersave/performance runs exited cleanly at 55.83 and
52.21 seconds respectively. Every policy restored to powersave. The Main
frame budget remains approximately 33.33 ms; faster CPU execution does not
change that configured pacing. No performance threshold is enforced from this
single comparison. Benchmark subsequent changes under temporary performance
policy and record actual frequency; choose a persisted product policy only
with power/thermal and physical display measurements.

## Final validation

The complete real-GL GUI runner passed against the final source, including
one/four-worker app-session, app-job, layout and expanded memory contracts;
viewport/focus/touch tests; all four onboard apps; refusal/retry; graphics death;
live render deadlines; storage drain and two normal boots. The final profiling
entry passed real desktop GL with normal drawing and retained pixels. The
retained run returned 523 frames, of which 436 retained existing pixels; those
frames did not fabricate new submission timings. Eight Python tests cover
correlation, mirrored logs, retained/coalesced frames, logical memory bounds,
and CPU restoration on success, command failure, HUP and interrupted wait.

The final physical Pi memory run completed 29 navigation cycles over 900.27
seconds of sampled workload (906.82 seconds including boot/shutdown), using
four workers, 1280x720 and the same 64 MiB arena cap that previously failed.
It exited zero after normal quit and storage drain. A separate 30.08-second
SIGTERM boot also exited zero, with no timeout or kill escalation. CPU stayed
at 600 MHz. Installed PID 279 and restart count zero remained unchanged.

| Counter | First sample | Last sample |
| --- | ---: | ---: |
| Live ARC roots | 14 | 14 |
| Reserved arena KiB | 46848 | 47552 |
| Shell owner bumped bytes | 11461664 | 11461664 |
| RSS KiB | 54016 | 56316 |

After discarding three warmup samples, all 26 remaining samples held 14 roots
and reserved memory stayed within 47040-47552 KiB. RSS grew 2300 KiB across the
whole run. The final logical-bound checker was applied to every prefix of this
collected run and its result is retained as `memory-summary.json`, separately
from the raw runner result. This is finite repeated-session evidence, not a
multi-hour reachability proof or physical input/scanout acceptance.

Raw evidence, including both earlier retention findings, exact source/build
hashes, screenshots and all timing runs, is retained under
`.qos/validation/gui-performance-20261014/`.

Final candidate SHA-256 (matching production-flags host; SDK pin unchanged):

| Artifact | SHA-256 |
| --- | --- |
| Pi host | `37a5ef2969af08c3c665bf43699bd25ccfca209ce639432cb634db1d95651dbe` |
| Memory diagnostic Main | `6114fb0bbca456add23a0e965321ea9a65d6288065cd7c2ce257b88b8b6d0668` |
| Timing diagnostic Main | `455b2d937dfe1c651bedad4defd5fb5149cd3295d13e0216ef84d7b97547950f` |
| App/pane memory contract | `193c599e53f35f73f853d7c55278fb1f2414b036f1a81ea669183396a50e6bc2` |
| Matching four-app seed | `f315e4a6b6bb0175c8353d31a821b12a56732b1711a890ac70305882a26c2dac` |
