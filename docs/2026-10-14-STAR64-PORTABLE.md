# QOS Portable on STAR64 Linux

Later update, 2026-10-14: [STAR64-POWERVR](2026-10-14-STAR64-POWERVR.md)
records successful hardware EGL rendering on the installed card. The CPU
renderer measurements below describe the earlier software trial.

Kind: implementation and physical hardware record. Added 2026-10-14.
Baseline: QOS `c6903c2`, FP-RISC `0f4f6c2`, plus the working-tree changes
in this task; codegen revision 41, Portable ABI 19. These are development
builds, not a release pinned by `fprisc.lock.json`.

The experimental assembly adapter is replaced by normal FP-RISC Linux RV64
support: `fpr build --target=linux-riscv64`, native Linux riscv64 detection,
LP64D context switching and executable/shared-module TLS. QOS adds `qrv64`
application/plugin images, RV64 import stubs and linker scripts, and the
same two-placement relocation verification used by the other Portable ports.
The Linux port uses Portable sockets, rather than selecting QOS Native's
Ethernet-frame policy merely because the CPU is RISC-V.

## Build with a Linux RISC-V toolchain

Set `FPRISC_ROOT` to the updated compiler checkout, with `make fpr` already
completed on the build machine. Set `CC_RV64` to a Linux RV64GC/LP64D compiler
with the target sysroot. The STAR64 build used:
`/home/dev/.cache/qosp-br/star64/host/bin/riscv64-linux-gcc` in the ARM64 VM.

```sh
export FPRISC_ROOT=/path/to/fprisc
CC_RV64=/path/to/riscv64-linux-gcc
OUT=/absolute/path/to/star64-portable
mkdir -p "$OUT"
make -C qos portable-es QOSP_ARCH=riscv64 QOSP_ES_OUT="$OUT/qosp" \
  FPRBUILD_EXTRA="--target=linux-riscv64 --cc $CC_RV64" SND_FLAGS= SND_LIBS=
python3 tools/main-profile.py --arch rv64 --cc "$CC_RV64" --output "$OUT/Main"
make qos-app APP_HOST=rv64 QOS_RV64_CC="$CC_RV64" \
  PROG=tests/blockportable.fpr QA_OUT="$OUT/blockportable.qa" BUILD="$OUT/block-build"
```

The EGL host needs target EGL/GLES development libraries in the sysroot.
The freestanding `.qa` images do not need libc, but use the same RV64GC
instruction set and LP64D calling convention. Every image/plugin is linked
at zero and 256 MiB; `mkqa --check-moved` verifies its relocation list.
On native riscv64 Linux, `make qos-app` selects RV64 automatically and uses
`gcc`; `QOS_RV64_CC` can override it.

Buildroot's optional QOSP package now passes `--target=linux-$(BR2_ARCH)`
explicitly. For a new appliance image, enable `BR2_PACKAGE_QOSP`, point its
QOS/compiler options at these updated trees, and select
`BR2_PACKAGE_QOSP_MAIN_PROFILE` with the built Main artifact directory.
The base STAR64 defconfig remains a text-login bring-up image. The existing
card was updated over SSH without reflashing or changing boot firmware.

## Installed card

- `/usr/bin/qosp`: EGL/GLES Portable host; `/usr/bin/qosp-headless`: text host.
- `/usr/share/qosp/app.qa`: Main; `/usr/share/qosp/Main.disk`: initial bundled apps.
- `/var/lib/qosp/Main.disk`: writable persistent state, copied only if absent.
- `/etc/init.d/S99qosp`: supervised boot service, with bounded readiness,
  restart and shutdown; `/var/log/qosp.log` and `/var/run/qosp/state` record results.
- `/etc/default/qosp`: optional board settings, loaded by both service paths.
  This card uses four workers, a 512 MiB app arena and full-display scaling.
  The optional LLVMpipe bundle selects a 960x600 raster; the softpipe fallback
  uses 480x300, unlit UI and exact retention of unchanged frames.
- `/opt/qosp-llvmpipe`: separately installed, checksum-pinned Debian RISC-V
  Mesa 25.0.7 and LLVM 19.1.7 runtime. The service uses private library/driver
  paths; the original Buildroot Mesa remains installed.
- HDMI text login moved to `tty2` (Ctrl+Alt+F2); graphical output uses `tty1`.
  `/etc/inittab.before-qosp` preserves the previous configuration. SSH remains
  public-key authenticated at the board's DHCP address, currently `192.168.0.151`.

```sh
/etc/init.d/S99qosp status
/etc/init.d/S99qosp stop
/etc/init.d/S99qosp start
tail -50 /var/log/qosp.log
```

Main uses arrows/Enter to select/open, Page Up/Down to change pages, Escape
to return home, P to save a PPM snapshot in `/tmp`, and Q from home to quit.
The service treats an application exit as a restart request while running;
use the service's `stop` command for a lasting shutdown. Ctrl+Alt+F1 returns
to the graphical virtual terminal.

## Evidence

The physical board is the 4 GiB STAR64 running Linux 5.15.131 and Buildroot
2026.08. The working UGREEN reader/microSD Express card is retained; the
previous SanDisk 400 GB/reader failures are recorded in the October 13
[hardware boot report](2026-10-13-STAR64-HARDWARE-BOOT.md).

- All 17 normal FP-RISC Linux RV64 cases passed: arithmetic, vectors, actors,
  parked wakeups, stdin/stderr, shared Int/F64 modules at one/four workers,
  and FP register/fcsr/TP/GP context preservation. No assembly patching.
- Routed block storage returned `query=True config=True write=True read=routed HOLDS`.
- An RV64 plugin loaded from QLOG disk and returned `40+2=42`; the same plugin
  ran under a second shell. Missing imports and tampered RELOC bytes refused
  by name/digest before entry.
- Main loaded Clock, Logs, Browser and Disk plugins, then published readiness
  at four workers. Offscreen keyboard replay changed pages and Browser state,
  opened Clock and produced five checked 960x600 snapshots. Returning home
  and quitting drained/flushed storage and ended normally.
- With frame retention enabled, a separate Main replay verified identical
  unchanged snapshots, different page/Browser pixels, animated Clock pixels,
  and graceful storage drain. This protects against retaining stale content.
- The installed host acquired `/dev/dri/card0` at 1920x1080, centered its
  960x600 render target, and discovered the Logitech USB receiver keyboard.
  The user confirmed that the graphical screen appeared. Keyboard response
  is under investigation; discovery alone does not establish usable input.
- Main used approximately 110 MiB RSS with LLVMpipe (103 MiB with softpipe) after startup, with a 512 MiB app-arena
  cap. The host also reserves a much larger virtual range for its Base
  runtime; VmSize is not resident RAM. No swap is configured.
- Existing macOS POSIX modules/MVU and x64/AArch64/RV64 ELF module artifacts,
  the complete macOS Base suite, ESP-IDF TLS and service lifecycle checks passed. The service checks include
  board configuration reaching the supervised child. Pixel-only scanout
  tests passed RGB order, vertical orientation, stride, native/fit/fill modes;
  the post-build console check passed baseline tty1, QOS tty2, repeated builds
  and conflicting-getty refusal.

Artifacts and logs for this development run are under
`.qos/star64/2026-10-14-port/`, including `fpr-tests/results.json`,
`qos-probe-results.log`, Main snapshots and `installed-status.log`.


## Reproduce the optional faster renderer

[LLVMpipe](https://docs.mesa3d.org/drivers/llvmpipe.html) compiles shaders on
CPU cores. The physical trial uses an isolated Debian runtime bundle instead
of replacing the working Buildroot libraries. Its 41 exact package versions
and SHA-256 digests are in `tools/buildroot/star64-llvmpipe.json`.

On the Linux build machine (with `dpkg-deb`):

```sh
python3 tools/buildroot/star64-llvmpipe.py --output /path/to/llvm-bundle
```

The builder verifies every package, extracts without installing packages or
executing maintainer scripts, and creates `bundle.tar.gz` plus a manifest.
Retain the package copyright/license files carried under `usr/share/doc`.
On the board, extract into a staging directory using `gzip -dc ... | tar -xf -`,
then install the contents of `bundle/` under `/opt/qosp-llvmpipe` and its
manifest alongside them. The tracked STAR64 `/etc/default/qosp` selects this
private stack when present. Stop the service before changing its renderer;
start it again after installation. The deployed root partition must have
space for approximately 200 MiB of libraries.

For a future image built wholly from source, Buildroot exposes
`BR2_PACKAGE_MESA3D_LLVM` and `BR2_PACKAGE_MESA3D_GALLIUM_DRIVER_LLVMPIPE`;
that LLVM 22/Mesa 26 build has not been validated here. The pinned Debian
bundle is a separate deployment artifact, not a replacement Buildroot sysroot.

Frame-retention and display settings are optional HAL settings:

| Setting | Effect |
|---|---|
| `FPR_GFX_SIZE=WxH` | Override EGL raster size, including an attached display |
| `FPR_DRM_SCALE=fill` or `fit` | Fill the monitor or preserve the canvas aspect ratio |
| `FPR_DRM_TTY=/dev/tty1` | VT held in graphics mode while KMS is active |
| `FPR_GFX_RETAIN_UI=1` | Retain an exactly unchanged 2D frame with an empty 3D background |
| `FPR_GFX_UNLIT_UI=1` | Skip per-pixel 3D lighting for flat UI geometry on slow CPU renderers |
| `FPR_GFX_TRACE=1` | Log draw/presentation timing and retained frames |

## Limits

Graphics are CPU-rendered: the installed LLVMpipe provides OpenGL ES 3.2,
with the original softpipe/ES 3.1 stack retained as fallback. No PowerVR
acceleration or RVV is required or claimed. The vendor kernel, Wi-Fi, sound and the second
Ethernet port remain outside this port's validation. Native GHC/compiler
bootstrapping on the board and a complete rebuilt/flashed Buildroot image
containing QOS, and a board reboot after this installation, have not been
tested. The 512 MiB root partition has about 79 MiB free after the optional
200 MiB renderer bundle; the rest of the card remains unallocated. Release packaging must commit FP-RISC
and update QOS's compiler pin before cutting a release.
