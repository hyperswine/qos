# Main idle CPU: retained MVU frames and real worker wakeups

Kind: implementation and physical Pi validation record, 2026-10-15.
QOS source base `b67f426c470b12f2cc27fd8e8d47cdebf303607c` plus the accompanying
idle-CPU patch; exact artifact/source hashes are retained in
`.qos/validation/pi-idle-20261015/bundle/manifest.json`.
FP-RISC pin: `302fc366a5c5fe41e433e2771946f9c591a6716e`, a maintenance branch
from the previously deployed SDK. The local selected SDK worktree is
`/private/tmp/fprisc-layout-20261014` (`codex/mvu-retained-20261015`).

## Change and ownership

The former shell rebuilt its full scene and submitted it about 30 times per
second even on unchanged Home. The new `std/mvu.runRetainedResultWithin`
opt-in driver still collects input, event ports and ticks at the configured
cadence, but calls the view/render worker only when the app's complete visual
key changes. Its first frame always renders. Renderer and worker death remain
checked on idle turns, and changed-frame calls retain their deadlines.
Ordinary `run`, `game` and live-reload paths continue rendering each turn.
A retained app promises its view depends on model/environment values and its
key accounts for every visible change; external facts must arrive as messages.

Main maintains a monotonic render revision through its normal recursive MVU
update. Its visible projection includes layout, focus, hover, child pane
phase/rows/scroll, clock, application tree, dynamic slot values and status.
Transport acknowledgement revisions are excluded. Snapshot requests also
invalidate the frame. No callback registry or application hooks were added.
The app-session owner drains queued replies and parks on its owning actor;
owner death wakes the receive and runs its existing cleanup.

The remaining platform overhead came from `qos/appside/hal.c`: worker IPI and
timer methods were no-ops and `wfi` slept for 200 microseconds before polling
again. Portable interface v20 appends explicit worker wait/ring/clear/timer
operations. The host implements these as separate per-worker pthread condition
variables with a latched bell, monotonic deadlines and the existing Unix
runtime's 20 ms fallback bound. MVU policy remains in FP-RISC, with scheduling in its existing runtime;
this C layer only provides OS sleep/wake. The host runtime and the loaded
application do not share park state. The host, Main and every onboard archive
must be replaced together across this interface change.

## Measurements and checks

All Pi comparisons used four application workers, 1024×600 and the unchanged
powersave CPU policy at 600 MHz. CPU percentages below use one full core as
100%, derived from process counter differences rather than load average.

| Measurement | One-core CPU |
|---|---:|
| Installed old Main, actual HDMI, preceding 120-second observation | 94.4% |
| Isolated old Main, offscreen V3D, steady 20-second sample | 66.58% |
| Isolated final candidate, offscreen V3D, steady 30-second sample | 9.43% |
| Installed final Main, actual HDMI, 180-second observation | 6.51% |

The installed session remained PID 296 with zero automatic restarts throughout
the isolated measurements. Offscreen comparisons do not include HDMI scanout
cost or prove physical panel latency. The installed comparison shows a 93.1% reduction in QOS CPU consumption at
the same clock policy; the offscreen pair separately isolates the implementation
change while production remained running.

Validation completed:

- Complete real desktop GL Main suite: responsive 1024×600/720p/1080p layout,
  scrolling, pointer cancellation, focus, all four onboard apps, close/reopen,
  refusal/retry, graphics death, live render deadline, storage drain and two boots.
- FP-RISC deadlines/task failures/retained MVU and legacy MVU reload, scoped
  state, event-port ownership and service-failure suites on one/four host workers.
- Retained MVU contract on one/four physical Pi workers: three changed frames
  across at least twenty input polls; unchanged-key renderer death; changed-frame
  deadline; ordinary animation still renders each turn.
- Portable parking: pending bells, clear/cancel, timed wake and 2,000 racing
  notifications, on macOS and ARM64 Linux.
- Pi app-session lifecycle contracts on one/four workers, including blocked
  owner death and stale replies.
- Production candidate: four navigation cycles in 115.24 seconds, normal quit
  with storage drain, and a second 30.08-second run stopped cleanly by SIGTERM.
  No forced termination. Production stayed untouched during these checks.
- Upgraded writable-disk memory preflight: seven navigation cycles over 316
  sampled seconds; all eight samples retained fourteen roots, with allocator
  reservations constant at 47,552 KiB after warm-up. Normal quit and SIGTERM
  shutdown both completed cleanly.
- Writable disk updater: ten regressions; upgraded copy preserves fourteen
  committed records, generation 7→9, log head 2469→3857.

Raw logs, manifests, samples and later HDMI captures remain under the ignored
local evidence directory above. The initial desktop test lacked display access
inside the sandbox; its unchanged graphics check passed with display access,
and the full GUI suite was restarted with that access. Its failed run is kept
as environment evidence.

## Deployment verification

Installed the matching v20 host, normal Main, all four apps, fresh seed and
upgraded writable disk after all preflight checks. The stopped original host,
shell, seed, writable disk and service configuration are retained on the Pi in
`/var/lib/qosp/deployment-idle-20261015/original.tar.gz`, with hashes and
`rollback.sh`. Restoring that writable disk later would discard intervening
writes; retain a fresh stopped snapshot before restoring if needed.

Installed KMS acceptance passed: all four apps, changing clock values, Files
scroll/refresh, focus navigation, touch capture/cancellation, Browser `/logs`
read and two further rounds of close/reopen. Temporary private replay input
was removed from the running configuration afterwards; normal Logitech K400
Plus and other device discovery is restored. No profiling or test hotkeys are
installed. The final service is PID 11323, with zero automatic restarts.

The normal installed HDMI session then completed a 180.48-second read-only
observation with seven samples: CPU averaged 6.51% of one core; RSS rose from
55,692 to 55,996 KiB during warm-up and remained exactly 55,996 KiB from the
second minute onward (54.68 MiB). Temperature was 49.173–50.634°C, with every
CPU frequency sample at 600 MHz. The service PID and log hash stayed unchanged.
A new KMS readback after the observation matched the previous Home pixels
byte-for-byte, confirming the retained frame remained selected for scanout.
Global GPU memory counters were unavailable. This is a short verification,
not an overnight memory bound or physical input-latency measurement.

There was no OS reboot during this change: the boot ID stayed
`bcd1ddf2-9cb6-41e1-9121-2e5c839ffedf`. Manual supervised restarts used for
deployment/input acceptance are distinct from automatic restart count.
The filesystem retained 75,268 KiB free after rollback retention. Installed
host, shell, seed and upgraded writable-disk hashes matched the manifest.
The earlier observed reboot, followed by over twenty-two hours of successful
startup/use, is useful recovery evidence if user-initiated; the prior volatile
logs cannot establish its cause or prove a general power-loss guarantee.

Evidence: `summary.json`, `installed-state.txt`, `final-state.txt`,
`remote-ui-result.json`, `observed-home.png`, `desktop-gui.log`,
`preflight/complete.json` and `memory-preflight/complete.json` beneath the local
validation directory. Source and SDK changes remain local for review; no
remote Git push was performed as part of this fix.
