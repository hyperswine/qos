# STAR64 hardware EGL rendering

Kind: implementation and physical hardware record. Added 2026-10-14.
Applies to the STAR64 card running the Fishwaldo Linux 5.15.131 kernel from
`1456c984f15e21e28fb8a9ce96d0ca10e61a71c4`, plus the Linux RV64 Portable
working-tree implementation described in [STAR64-PORTABLE](2026-10-14-STAR64-PORTABLE.md).
This supersedes that trial's software-only graphics boundary on the installed
card. The saved Buildroot SD image has not been rebuilt with these additions.

## Result and cause

The JH7110 PowerVR BXE-4-32 GPU works with hardware EGL and OpenGL ES 3.2.
The existing `pvrsrvkm` kernel module was already version **1.17.6210866**,
but its initial probe failed because both GPU firmware files were absent:

```
rgx.fw.36.50.54.182
rgx.sh.36.50.54.182
```

The exact matching StarFive DDK 1.17 package supplied those files and the
proprietary RISC-V userspace libraries. A separate Mesa 22.1.3 build with
StarFive's PVR Gallium patches connects EGL/GLES to that driver. Current
system Mesa and the optional LLVMpipe bundle remain installed.

Sources are pinned by URL and SHA-256 in `tools/buildroot/star64-powervr.json`:

- [StarFive GPU binaries](https://github.com/starfive-tech/soft_3rdpart/tree/b60da16be1b36453aa46599889c28310fd148fb8/IMG_GPU/out), DDK 1.17.6210866.
- [StarFive Mesa integration](https://github.com/starfive-tech/buildroot/tree/70e7c10de57195237ee4ae95f3c87637a39429b0/package/mesa3d), Mesa 22.1.3 and 63 patches.

The builder also guards Mesa 22's emulated `once_flag`/`call_once` declarations
when glibc already exposes them through `stdlib.h`. This is required by this
image's glibc 2.44 toolchain. Do not substitute the newer vendor 1.19 package
for this kernel's 1.17 userspace/firmware pairing.

This uses the vendor PVR Gallium bridge, rather than Mesa's upstream PowerVR
Vulkan driver. [Mesa's support table](https://docs.mesa3d.org/drivers/powervr.html)
still lists BVNC 36.50.54.182 as unsupported in the upstream driver.

## Reproduce the runtime bundle

On the Linux build machine, after building the STAR64 baseline:

```sh
python3 tools/buildroot/star64-powervr.py \
  --buildroot-output /home/dev/.cache/qosp-br/star64 \
  --output /home/dev/star64-gpu/repro/build
```

The builder downloads and verifies all sources, cross-compiles with the
image's SDK, and creates `bundle.tar.gz`. It installs nothing on the board.
Its output directory contains the source archives and patched Mesa sources;
retain those and the vendor's original package with any distributed artifact.
The runtime includes the Mesa license text and the vendor init-script reference.
The proprietary vendor libraries retain their original licensing status.

The fresh build used for deployment produced archive SHA-256
`7c127ac0315447428c7af7164788397d176f78c05fd420a0462553b9f386747b`.
Archive timestamps can differ across builds; source/package hashes are pinned.

The installed layout is:

```
/lib/firmware/rgx.fw.36.50.54.182
/lib/firmware/rgx.sh.36.50.54.182
/opt/qosp-powervr/mesa/usr/lib/
/opt/qosp-powervr/vendor/usr/lib/
/opt/qosp-powervr/manifest.json
```

Extract with `gzip -dc bundle.tar.gz | tar -xf -` on this BusyBox image;
its `tar` does not implement `-z`. Copy `bundle/` to `/opt/qosp-powervr`,
and its two firmware files to `/lib/firmware/`. The `/opt` copies of the
firmware are deployment references; the kernel loads `/lib/firmware/`.
Check kernel/version compatibility before installing on another image.

In the physical trial the GPU was unbound after its failed boot probe.
After installing firmware, writing `18000000.gpu` to
`/sys/bus/platform/drivers/pvrsrvkm/bind` retried only that device. It loaded
both files and created `card1` and `renderD128`; `card0` remained the HDMI
display controller. Rebinding after the failed probe logged an
`Unbalanced pm_runtime_enable!` warning, followed by successful initialization.
The HDMI driver was not unloaded and no boot firmware was replaced.

## Selection and recovery

The tracked STAR64 `/etc/default/qosp` selects the private PowerVR libraries
when the bundle and render node exist. It removes LLVMpipe-specific variables.
If the GPU is absent, the existing LLVMpipe/software choices remain available.
This availability check is not an automatic rollback after a later GPU fault.

Main requests a fixed 960x600 logical canvas. Leaving `FPR_GFX_SIZE` unset
centers that canvas; a 1920x1080 HDMI mode alone does not enlarge it. The final
GPU configuration uses `FPR_GFX_SIZE=1280x800`, `FPR_DRM_SCALE=fill` and
`FPR_DRM_GPU_BLIT=1`: a higher resolution raster with the same logical aspect,
scaled to the full monitor by the GPU. A 1920x1200 raster also passed replay
checks, but was slower and was reduced for interactive use.
The LLVMpipe fallback retains 960x600 and softpipe retains 480x300.

The previous card configuration is saved as `/etc/default/qosp.before-powervr`.
To select the installed CPU fallback for one service launch:

```sh
/etc/init.d/S99qosp stop
QOSP_RENDERER=llvmpipe /etc/init.d/S99qosp start
```

For a persistent CPU fallback, set `QOSP_RENDERER=llvmpipe` at the beginning
of `/etc/default/qosp`. `QOSP_RENDERER=softpipe` selects system Mesa instead.
The service must be stopped before changing the installed renderer/configuration.
`LIBGL_ALWAYS_SOFTWARE=1` is selected for the CPU renderers, so the presence
of the GPU node does not make system Mesa try to load an unavailable PVR driver.
Both CPU EGL pixel checks passed after the GPU was enabled.

The previous executable is saved as `/usr/bin/qosp.before-gpu-blit`.
To keep GPU rendering but use CPU presentation, unset `FPR_DRM_GPU_BLIT`
after the renderer-selection block in `/etc/default/qosp`, then restart.
An unsupported dma-buf import or failed GPU transfer also logs the reason
and falls back to CPU presentation automatically within the host.

## Physical evidence

- The kernel loaded matching firmware and initialized `pvr 1.17.6210866`.
- The vendor offscreen triangle test rendered ten frames, exited successfully,
  and produced a checked 1280x1024 PPM containing the expected triangles.
  Its short-run FPS report is not a QOS performance measurement.
- `star64-egl-check` against both the staged and installed private runtime
  reported `Imagination Technologies / PowerVR B-Series BXE-4-32`,
  `OpenGL ES 3.2 build 1.17@6210866`, and pixel `64,128,191,255`, GL error 0.
- QOS `gfxsmoke.qa` initialized the GPU context/shaders and saved its image.
- Independent Main replays at 960x600 and 1920x1200 passed identical unchanged frames,
  changed page/Browser frames, animated Clock frames and graceful storage
  drain. It used a separate test disk and network port, without stopping
  the displayed session. The home snapshot was visually inspected.
- The installed Main service opened the GPU render node and mapped the private
  PowerVR libraries. HDMI remained 1920x1080 and the Logitech keyboard was found.
  The user confirmed correct content and very responsive input on the initial
  centered canvas. After the full-display CPU copy proved slower, GPU
  presentation and the final raster were installed; the user confirmed
  **full screen and responsive**.
- `tools/buildroot/star64-gpu-scanout-check.c` passed on a separate 1920x1080
  display-controller buffer: EGL dma-buf import, GPU rendering, scaling,
  vertical flip, all four expected RGB corners, CPU-visible results and
  resource cleanup. A 100-iteration transfer-only sample averaged about
  2.1 ms per GPU blit. It does not measure the real scene's rendering time.
- QOS logged `GPU scanout blit: dma-buf XRGB 1920x1080, no CPU readback`.
  Sampled final full-screen frames took about 30-50 ms in presentation plus
  1-3 ms for CPU draw submission. Presentation's `glFinish` includes waiting
  for the scene rendering, so these timings do not separate GPU draw and
  transfer costs. CPU presentation at 1920x1200 had taken about 130 ms.
- Main used about 31 MiB RSS in the final 1280x800 session (about 40 MiB
  in the 1920x1200 trial), versus about 110 MiB in the earlier LLVMpipe trial.
  This is sampled process memory,
  not total GPU/kernel memory. The root filesystem has about 36 MiB free.
- The bundle builder passed a fresh cross-build; service lifecycle checks
  passed, including board configuration propagation and bounded shutdown.

Logs, replay images, source downloads and the tested bundle are under the
ignored `.qos/star64/2026-10-14-gpu/` artifact directory. A full board reboot
verified firmware initialization, the GPU render node, SSH and QOS autostart.
The GPU-presentation host was added afterward and verified through service
restarts. The firmware, final runtime/host and configuration persist on the
card; the saved SD image still needs rebuilding for this complete setup.

Final presentation exports the display controller's linear XRGB dumb buffer
as a dma-buf, imports it as an EGL image/renderbuffer, and GPU-blits the scene
into it with scaling and vertical flip. It avoids per-frame CPU readback and
CPU pixel copies. The existing CPU path remains available when disabled or
unsupported. This still uses a GPU copy and one live scanout buffer with
`glFinish`; it is not direct rendering with double-buffered, vblank-synchronized
page flips. Tearing, long-running stability and other boards are not established
by this trial.
