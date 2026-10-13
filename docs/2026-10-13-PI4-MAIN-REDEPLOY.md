# Pi 4 Main production redeployment - 2026-10-13

The normal Main profile is deployed to the Pi at `192.168.0.233` under the
existing Buildroot supervisor. This replaces the application bundle and
Portable host; it does not reimage the OS. All original committed writable
disk records were retained, and the previous installation is saved for rollback.

## Build and installation

- QOS application source: `c1a10a0f4984b54934c9baa66285e21158bd461f`.
- FP-RISC: the exact `fprisc.lock.json` pin,
  `bfbdd8dea2c0b9cc2ab39801e060092e2069aa66`.
- Entry: `programs/main.fpr`, with matching `clock`, `logs`, `browser` and
  `disk` GUI archives. No reliability/memory probe entry or
  `QOS_BLK_TEST`/`QOS_STORE_TEST` flags. The built host contains none of the
  `QOS_BLK_TEST_*`/`QOS_STORE_TEST_*` environment strings.
- Archives: AArch64, Ubuntu Clang 18.1.3; Portable ES host: the Pi Buildroot
  AArch64 GCC 13.4.0 SDK, ALSA enabled.
- Host installed at `/usr/bin/qosp`; shell at `/usr/share/qosp/app.qa`;
  fresh seed at `/usr/share/qosp/Main.disk`; upgraded writable disk at
  `/var/lib/qosp/Main.disk`.

The existing disk had valid v3 superblocks at generations 2/3. A clean
supervisor stop completed before its final snapshot; that snapshot exactly
matched the earlier candidate source. `tools/pi4/update-main-disk.py`
verified all six committed records and appended the four replacement archive
records. Pages 1 through 592 remain byte-for-byte intact. The committed head
advanced from 593 to 1081, with both fallback slots publishing the new bundle
at generations 4/5. No user history or app index was replaced.

| Artifact | SHA-256 |
| --- | --- |
| Portable host | `70b0ecf5ede692662a6add46c852f517da79a00b77afb118404d7d2a4b13463a` |
| Main shell | `d6504764c5b68b88d6b16a3984cc02c7c731035bf908b3b2a229a3f5c5ff6d70` |
| Fresh seed | `d411a8628054f557e0c5f6133bdffc9eb3c50d604ac1f198408cccc8801dbcce` |
| Original stopped disk | `5bb42bd6ae3f20f6eceee1daf1f52c88109ede1cf35e12557f7ed372cdb7619e` |
| Upgraded writable disk | `e74141cbd3b05cc54a5ca37ab8c3508c73d73bcb01e128decc73b4a33982fdae` |

Rollback files are on the Pi in `/var/lib/qosp/deployment-main-20261013/`:
`qosp`, `app.qa`, `seed.disk`, `Main.disk`, and before/installed hash manifests.
Stop the supervisor before restoring all four matching files. Preserve the
current writable disk separately if restoring later: the original rollback
disk cannot contain writes made after deployment. The installation script
included automatic restoration if copying or startup failed; that path was
not needed or fault-injected. Approximately 82 MiB remained free on root.

## Fresh validation

- Ten offline updater checks passed: record history, binary user values,
  tombstones, bulk records, both fallback slots, corrupt metadata/payloads,
  pending operations, record bounds, conflicting generations, full disk,
  custom index, exclusive output creation and unchanged source on refusal.
- Before installation, the normal production bundle ran on real Pi EGL/V3D
  with an isolated copy of the upgraded writable disk: three Files/Logs/Browser
  navigation cycles over 73 seconds, then normal quit with storage drain.
  A second boot completed a separate SIGTERM shutdown after 30 seconds.
  Both exited zero without kill escalation; maximum RSS was 47,892 KiB.
  This candidate rendered offscreen while the old service owned the display;
  its launcher snapshot was also inspected.
- The installed host and shell hashes matched the build, and all four
  replacement plugins attached successfully. The session acquired real KMS
  scanout on `/dev/dri/card1`, 1024x600, with the 960x600 frame centered.
  EGL reported V3D 4.2.14 / OpenGL ES 3.1 Mesa 24.0.9. The Logitech K400 Plus
  keyboard and mouse were detected.
- A clean supervised stop/start succeeded after installation. The writable
  disk hash stayed unchanged across it. The resulting ready PID was 30144,
  with `restarts=0` throughout four samples over 60 seconds. RSS was
  44,248-44,504 KiB. No new panic, segmentation fault, fatal log or display
  ownership error was observed.
- CPU governor was `powersave`: 600 MHz observed, 1.5 GHz configured maximum.
  These checks establish deployment and short runtime acceptance, not a
  full-speed performance baseline, power-loss proof or physical reboot test.

Local ignored evidence is in `.qos/pi4/deployment/main-20261013/`: exact bundle
and toolchain manifests, original/upgraded disks, build/install/restart logs,
candidate workload results and snapshot, and installed observation samples.
The ARM64 production build log is `/tmp/qos-pi4-production-build.log`.

## Next Main/GUI work

1. **Visible service-error recovery.** Present storage/network failure state
   with useful details and explicit Retry/Home actions while the UI services
   remain available. Do not replay writes whose outcome is uncertain. Keep
   renderer failure diagnostics across a supervised session restart. Current
   loop failure cleanup is bounded, but `guishell.fpr` ends the session on an
   unrecoverable loop/service error.
2. **A versioned app session contract.** Add explicit close/cancel and ownership
   cleanup for background actors/subscriptions, plus a checked plugin contract
   before invoking GUI exports. Current `Mod.findAt` checks export presence;
   plugins run cooperatively in the same process and can still trap or block
   it. Process isolation is a later, distinct boundary.
3. **Responsive layout and complete input.** Replace the fixed 960x600 geometry
   and hard-coded tile/hit regions with viewport-derived layout, UI scaling,
   focus rules and tested keyboard/mouse navigation. Validate the physical
   panel plus 720p/1080p displays; complete raw Pi wheel/touch handling where
   supported.
4. **Measured responsiveness.** Select and record a CPU policy for benchmarks,
   then instrument frame time, input-to-present latency and allocation during
   repeated app transitions. Measure the Pi readback/scanout path before
   choosing rendering optimizations. Retain the longer reliability soaks as
   separate evidence rather than interpreting them as performance results.

Relevant implementation: `programs/mods/guishell.fpr` (error cleanup, dynamic
GUI exports, layout/input), `programs/mods/qsys.fpr` (managed services),
`hal/unix/gfx.c` and `hal/unix/drm_scanout.h` (render and display presentation).
