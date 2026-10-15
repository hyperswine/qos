# STAR64: current FP-RISC with retained rendering

Kind: implementation and physical-board validation record, 2026-10-16.
QOS source base `b67f426c470b12f2cc27fd8e8d47cdebf303607c` plus the current
Portable v20 and GUI working-tree changes. FP-RISC pin:
`573cfd346aad714c9e4ebc117733b0d7c416c6b9`.
Exact source and artifact hashes are retained locally under
`.qos/validation/star64-upgrade-20261016/` in `source-manifest.json` and
`bundle/manifest.json`. This is a board deployment record, not a published
release or a rebuilt SD image.

## Integration

Ported the retained-rendering change from maintenance commit
`302fc366a5c5fe41e433e2771946f9c591a6716e` onto FP-RISC main revision
`4bba11b52b82c5a82c5f752658e0f3646184312a`. The resulting local commit is
`573cfd346aad714c9e4ebc117733b0d7c416c6b9`, on
`codex/star64-retained-20261016` in the sibling
`fprisc-star64-upgrade` worktree. The original FP-RISC checkout's unrelated
RV32 work was preserved. FP-RISC main now publishes this exact commit; QOS
pins it in the accompanying integration commit.

The opt-in MVU driver skips unchanged frames while retaining first-frame
rendering, input/event polling, renderer/worker death checks and changed-frame
deadlines. See [the idle CPU implementation](2026-10-15-GUI-IDLE-CPU.md) for
the Portable v20 worker sleep/wake operations and the retained-view contract.
Rebuilt the RV64 host, Main and Clock, Logs, Browser and Disk archives together;
mixing the old host and new application across this ABI change is unsupported.

The legacy raw block-device contract now explicitly declares `unsafe program.`
as required by the current compiler. QOS's lock check resolves all 241 pins.
The ignored local SDK selector points at the combined worktree above.

Builds used an isolated Linux VM source snapshot and the existing STAR64
Buildroot RV64 cross-toolchain. Latest FP-RISC's native Git adapter required
libgit2's current backend-query API; libgit2 1.9.1 was built in an isolated SDK
prefix instead of modifying the compiler to accommodate the old VM library.

## Validation

- Host compiler: deadline/task-failure/retained-MVU checks and legacy MVU
  reload, scoped state, event ports and service-failure checks on one/four
  workers; Linux RV64 lowering, link flags, TLS/context and cache isolation.
- Full desktop GL Main suite: panel/720p/1080p layouts, keyboard and touch
  replay, focus/cancellation, all four apps, scrolling, close/reopen,
  refusal/retry, graphics failure, render-worker deadline, storage drain and
  two boots.
- Physical STAR64: 17 native RV64 runs covering floating point, vectors,
  actors, sleep/wake, text, context switching and dynamic modules.
- Physical STAR64: 26 further one/four-worker cases covering retained MVU,
  deadlines, task/actor failure, image ownership, GUI/app sessions/jobs,
  session memory, raw block storage, storage deadlines and Files shutdown.
- Portable parking checks include pending bells, timed wake, cancellation and
  2,000 notification races. Disk updater regressions passed all ten cases.
- Isolated Main used an upgraded copy of the actual writable disk on SD,
  four workers and real offscreen PowerVR EGL at 1280×800. Seven navigation
  cycles completed over 180.63 sampled seconds. All seven memory samples
  retained 14 roots. Reserved allocator memory ranged from 47,040 to
  47,552 KiB after warm-up; the owner bump counter stayed at 10,950,704 bytes.
  Normal quit and a second SIGTERM run drained storage without forced kills.
  This is a bounded observation, not proof of indefinite memory stability.

## Deployment and recovery

The stopped original host, Main, seed disk, writable disk and configuration
were backed up before replacement. The updater preserved all five committed
records and appended the four matching app archives: log head 475→1799,
generation 2→4. Sparse copies preserve every byte while avoiding allocated
zero blocks. The installer checked both original and candidate hashes,
installed the matching bundle, and checked readiness, ABI v20 and PowerVR.

| Installed file | SHA-256 |
|---|---|
| `/usr/bin/qosp` | `2642dd2aac4a35803d2ebccf907836722d8c09ef42b213e537b9c9bb82e75dad` |
| `/usr/share/qosp/app.qa` | `35c2f4c756751e138d4ec2d35d9c84d07ae066c340154655a9af99511bd9f4e4` |
| `/usr/share/qosp/Main.disk` | `7ece507de49b117fd04f770ad2a1a9fa67f2b5ec9a4a50bb45ba19bf10064f6a` |
| `/var/lib/qosp/Main.disk` immediately after upgrade/reboot | `bf49f25ee34d2eb0c42f1402b158bcf8f8c26207644e1f84cd9bcf8c603d1348` |

Persistent board rollback directory:
`/var/lib/qosp/deployment-star64-upgrade-20261016/`.
It contains `original.tar.gz`, original/installed hashes, the candidate
manifest and executable `rollback.sh`. Restoring it also restores the old
writable disk; preserve a fresh stopped snapshot first if there have been
subsequent writes. The installer also had automatic rollback on startup
failure. Keep backups outside `/etc/init.d`.

## Reboot acceptance

The board rebooted into the unchanged optimized Linux 5.15.131 kernel (#3).
Boot ID changed to `fb621176-4612-455e-b81f-02d2192dc3a6`; the installed file
hashes above matched after reboot. Main ran as PID 285 with zero restarts,
published all four plugins and reported PowerVR B-Series BXE-4-32 / EGL 1.5 /
OpenGL ES 3.2. Public-key SSH recovered over Wi-Fi at `192.168.0.215`.
This boot reported Main readiness at 17.27 seconds and wireless link readiness
at 17.10 seconds from Linux startup. These are single-boot observations, not
SD power-on timing or a controlled boot-speed comparison.

An installed idle observation from uptime 81.52 to 142.16 seconds kept the
same PID and zero restarts. Process CPU counters increased by 817 ticks at
100 ticks/second: 13.47% of one core over 60.64 seconds. RSS stayed at
42,860 KiB (41.9 MiB); PSS measured 42,037→42,099 KiB. This headless sample
does not include connected-display scanout cost and is not an old/new CPU
comparison. Raw samples are in `idle.json` beside `reboot.log`.

The board had no attached HDMI display or keyboard for this upgrade. Physical
panel size, scanout and real keyboard responsiveness therefore still require
an attached-display check; the automated GUI suite and physical offscreen GPU
tests passed. The existing optimized kernel, Wi-Fi configuration and vendor
GPU stack were retained. No complete Buildroot/SD image was rebuilt or flashed.
