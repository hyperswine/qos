# Pi 4B runs the Main GUI shell from the SDK 0.6.1 app (27 November)

Kind: delivery record. Branch `pi-guishell-sdk-0.6.1`. The owner asked to rebuild the QOS Main
GUI shell (the `qos-guishell` repository, an SDK 0.6.1 app) for the Pi 4B and redeploy it,
backing up the current image first.

## What is installed

Everything is at the SDK 0.6.1 pair: qos `3d66631`, fprisc `151b3eeb`, ABI `24.262`. The Pi was
on ABI `24.239` (FP-RISC 0.14.0, [the 15 November install](2026-11-15-PI-FPRISC-0.14.0-INSTALL.md)),
and the host accepts only a plugin whose ABI string equals its own (`24.<codegen>`), so the
host, the shell, the onboard apps and the on-device compiler had to move together.

| File | sha256 | From |
|---|---|---|
| `/usr/bin/qosp` (`qosp-es`, ALSA) | `0be80ff8…` | qos `3d66631`, fprisc `151b3eeb`, built in `qos-pi-builder:20261127` |
| `/usr/share/qosp/app.qa` | `185a9c0e…` | `qos-guishell` (`ccfb29e`), `qos build` with SDK 0.6.1 on the Mac (the archive is OS-neutral: `aarch64`, ABI `24.262`) |
| `/usr/share/qosp/Main.disk` (seed) | `0ecc3351…` | `tools/mkdisk.sol` with the SDK's six profile apps |
| `/usr/share/qosp/compiler-sdk.tar.gz` | `dfa24a93…` | `tools/pi4/compiler-sdk.sol` at the pair, with the fixes below |
| `/var/lib/qosp/Main.disk` (writable) | `6e1d2dc6…` at install | the live disk, `mkdisk --preserve` with the six new apps |

**Rollback:** run `/var/lib/qosp/deployment-pi-guishell-19700127T182057Z/rollback.sh`. It
restores all six files and restarts fprd and Main.

**Full image backup:** both partitions of the SD card (32 MiB boot, 512 MiB root), copied with
root remounted read-only and Main and fprd stopped. They are on the Mac in
`.qos/pi4/image-backups/pi4b-before-guishell-20261127/` (`mmcblk0p{1,2}.img.gz`, the partition
table, and SHA-256 of the device and of the copies, which match), with the live writable disk
beside them.

## The builder

`qos-pi-builder:20261127` is FP-RISC's Linux build image (`packaging/linux/Dockerfile`: bookworm,
GHC 9.8.2, libgit2 1.9.1) plus `libegl-dev libgles-dev libdrm-dev libgbm-dev libasound2-dev
clang lld llvm patchelf`, run on colima (arm64).
- **glibc:** the host binary needs glibc 2.34 or newer; the Pi has 2.41.
- **Libraries:** it needs only `libEGL`, `libGLESv2`, `libm`, `libasound` and `libc`, all on the
  device.
- **DRM headers:** Debian keeps them under `libdrm/`, so the build adds an include directory where
  `drm/` points there.

## Faults found and fixed

1. **The compiler SDK's self-test pinned a stale `std/actor`** (`#201a0e9b…`). Today's compiler
   refuses it on the safety line, as 0.15.0 does. It now pins `#32ab963a…`, which checks.
2. **`make plugin-qa` runs its Sol tools as `$(FPRC) sol …`,** but on the device `FPRC` is the
   Editor entry, which has no Sol VM. The entry now hands `sol …` to `$SOL`, the SDK's Sol
   runner, which `qos-fprd` already sets.
3. **The `-O0` Editor compiler did not finish** a program using `std/actor` in ten minutes; the
   `-O1` build compiles it in a second. The doc's ghc line is now `-O1`.
4. **The new daemon could not start on the Pi:** `libGLdispatch.so.0` was not found. The
   compiler links EGL/GL for Sol's graphics, and the SDK bundles glvnd's `libEGL`. But a
   library's own dependencies do not use the executable's `$ORIGIN/../lib` runpath, and the
   container hid this because it has the library. The packager now sets every bundled library's
   runpath to `$ORIGIN` (`compiler-sdk-libs.sol`). Before installing, every library each bundled
   file needs was checked to be bundled or on the device.
   - The first install attempt stopped here and rolled back by itself.
5. **The SDK archive is 51 MB,** over the packager's default 40 MiB cap; it was 39 MB at 0.14.0,
   and the compiler is larger now. It was packaged with `--max-compressed-mib 56`. Unpacked it is
   179 MB, within the device's 512 MiB SDK RAM filesystem.

## Checks

| Check | Result |
|---|---|
| Staged hashes on the device | all five match |
| `qos-fprd selftest`, SDK unpacked in `/tmp` on the Pi | ok: check, plugin (QAR2, 136,458 bytes, `qa64`), publication committed-frozen-stable-updated (v1.1), invalid source refused |
| Disk migration | six app records replaced, apps index rewritten; the visible `/home` and `sys/` keys are the same before and after |
| Install, with rollback on any failure | fprd started and its self-test passed from `/run/fpr-sdk/root`; Main started: "hosting QOS Main GUI Shell (4 harts, abi v24)", the six apps published as plugins, scanout 1024x600 on V3D (Mesa 24.0.9), "Main Profile ready (10 shortcuts, 2 pages)", no ABI mismatch or panic; the same again after a restart |
| Fresh SSH | installed hashes match; Main running (RSS 63.6 MB; 59.5 MB at the 15 November install) |

Not checked:
- the shell driven through its pages and apps (there is no `/dev/uinput` to inject input);
- an HDMI readback;
- an Editor build through the live UI;
- a long soak.

## Housekeeping

- **Free space:** the failed first attempt's backup directory was a byte-identical duplicate of the
  second. It filled `/` to 100% until it was removed. `/` now has 79 MB free.
- **Left for the owner:**
  - the four older rollback directories, about 20 MB each;
  - the unset clock (1970).

## Files freeze and app reset (27 November)

The owner reported that the 1024×600 GUI froze while using Files on the
Pi 4 Model B Rev 1.4. SSH remained responsive. The installed host and app
SHA-256 values matched the deployment above.

- Before the reset, supervision still reported application PID 373
  running. The final shell messages were `shell: open files` and
  `shell: pane 1 R Refresh   ESC Home`, after visits to Disk and Browser.
  The Files pane had completed its initial load. The captured app log
  contained no panic or fault, and the kernel log tail showed no GPU
  fault or OOM event.
- In two samples 2.07 seconds apart, three QOS threads each accumulated
  206 user CPU ticks. The process's I/O counters stayed unchanged.
  This points to active spinning or repeated work after the pane load.
  The samples do not locate the user-space instruction or establish the
  triggering operation.
- Restarting only `/etc/init.d/S99qosp` timed out the old process during
  shutdown (status 124). PID 9568 then reopened `/data/qosp/Main.disk`,
  loaded all six plugins, and reported `Main Profile ready`. The new
  process had seven sleeping threads at both points of a short idle sample.
  No Pi reboot, disk replacement, or compiler-daemon restart was needed.

The restart restored Main readiness over SSH. Interactive Files behavior
after the reset was not exercised. Raw captures are in the Codex
workspace under `outputs/pi4-files-freeze-2026-11-27/`; the Pi's clock
was unset, so use uptime to order its captured events.
