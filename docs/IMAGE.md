# QOS Portable as a bootable image

QOS Portable normally runs as a program on somebody's Linux or macOS. This is
the other way to ship it: a Linux image built by Buildroot that contains
nothing but a kernel, Mesa, ssh, wifi and `qosp`, so that a Raspberry Pi 4
powers on and comes up inside an FP-RISC application, full screen, with no
desktop and no window system anywhere.

The tree that does it is [`tools/buildroot/`](../tools/buildroot/README.md),
which has the build and deployment instructions. This page is the why.

## The display stack is three things

`hal/unix/gfx.c` was written for this case long before there was an image to
put it in. It asks EGL for the **surfaceless** platform, renders the scene
into an offscreen ES 3.1 FBO, and `hal/unix/drm_scanout.h` puts each frame on
the monitor with raw DRM ioctls: find the first `/dev/dri/card*` that has a
connected connector, take its preferred mode, create one XRGB dumb buffer,
`SetCrtc` once, and blit the readback into the mapping per frame.

That is the whole path. `libEGL`, `libGLESv2`, and a DRM device — no X server,
no Wayland, no compositor, no GBM surface, no display manager, not even
libdrm. It is why an image like this is tens of megabytes rather than a
gigabyte, and why there is no login screen between power-on and the
application.

`drm_scanout.h` is also wholly optional and self-disabling: no `/dev/dri`, no
connected display, no DRM master, or `FPR_DRM=0`, and it renders offscreen
exactly as before, with one line in the log saying which. So the same binary
serves the Pi, a CI machine with no GPU at all, and the replay checks.

### Two things this arrangement gets wrong if you are not careful

Both were found by booting the QEMU image, and both would have bitten a Pi
just as hard.

**The scanout must be opened before EGL.** Only the DRM master may modeset,
and the master is whoever opened the primary node first. `eglInitialize`
opens it — Mesa's loader probes `/dev/dri/card*` looking for a driver. So an
EGL-first order silently hands Mesa the master and leaves the scanout with
`EBUSY` and nowhere to put a frame. `gl_init` therefore takes the display
first, always, and only then asks for a context. (We also ask for master
explicitly: the kernel's fbdev emulation has already opened the node to put a
text console on the screen, so we are never the first opener.)

**A paravirtual display does not scan out of the mapping.** virtio-gpu keeps
the real pixels on the host and copies only what it is told has changed, so
filling the dumb buffer perfectly leaves the screen black. `drm_scanout_present`
ends with a `DIRTYFB` ioctl naming the rectangle it wrote. Scanout hardware —
vc4 on a Pi — reads the memory directly and has no such ioctl, so the first
call there fails harmlessly and the code stops asking.

Input is the same shape. `evdev_raw.c` reads `/dev/input/event*` and
`mice_raw.c` reads `/dev/input/mice` — both of which a bare Linux console has,
with no window system to ask. See [INPUT.md](INPUT.md).

## What the build does and does not own

`qosp` is an FP-RISC program (`qos/portable/qosp.fpr`) whose HAL is the C
under `hal/unix`, and the thing that knows how to assemble those is
`qos/Makefile`. The Buildroot package therefore **calls that Makefile** —
its `portable-es` target — rather than keeping a second copy of the source
list. Three hooks exist for exactly that, and for nothing else:

| hook | what a cross build needs it for |
| --- | --- |
| `FPRBUILD_EXTRA=--cc <gcc>` | compile and link with Buildroot's toolchain |
| `QOSP_ARCH=<arch>` | decide `-ffixed-x28` by the TARGET, not the build machine |
| `QOSP_ES_OUT=<path>` | write the binary into Buildroot's build directory |

`fpr` stays out of Buildroot entirely. It is a Haskell program, it runs on the
build machine, and it only ever emits assembly for the target — so a package
that tried to build it would be building a compiler to build a compiler.

## Two targets, one path

| target | GPU | what it is for |
| --- | --- | --- |
| `qosp_qemu_aarch64` | virtio-gpu, Mesa swrast | the test loop |
| `qosp_rpi4` | vc4 (display) + v3d (3D) | the actual appliance |

They exercise the *same* code. QEMU's virtio-gpu gives a DRM device with a
connected connector, so the scanout takes it and presents through a dumb
buffer exactly as vc4 does; only the gallium driver underneath differs. That
is what makes the QEMU target worth having: a failure there is a real failure
on the Pi, not an emulation artifact.

`tools/buildroot/qosp-check.py` boots the QEMU image unattended and asserts
each link of the chain — the DRM device, EGL on the surfaceless platform, the
scanout engaging at the monitor's own mode, the renderer uploading meshes,
and finally the pixels themselves, dumped out of QEMU's display from *outside*
the guest so that nothing in the guest can claim success it did not achieve.

## The one line the Pi needs

`board/qosp/rpi4/config.txt` carries it:

    dtoverlay=vc4-kms-v3d

That is what makes the firmware hand the display to the open vc4 KMS driver,
so Linux exposes a `/dev/dri/card*` with a connector. Without it the Pi has a
framebuffer and no DRM device, and `qosp` renders offscreen into nothing
anyone can see.

## What it costs in memory

Measured 2026-09-21 on the QEMU target (Linux 6.12, 4 CPUs, 2 GiB), with
`/proc/meminfo` after `drop_caches`, against the Ubuntu 24.04 cloud image
`tools/arm64-vm` boots (same RAM, same CPUs, idle):

| | Buildroot image | Ubuntu 24.04 server |
| --- | --- | --- |
| occupied at idle, of 2 GiB (physical − MemFree) | ~97 MiB | ~257 MiB |
| of which the kernel reserved at boot | 55 MiB | 93 MiB |
| user processes (AnonPages) | 3 MiB | 28 MiB |
| kernel slab | 10 MiB | 45 MiB |
| page cache that survives `drop_caches` | 7 MiB | 41 MiB |
| processes, kernel threads included | 76 (10 in userspace) | 110 (12 running services) |
| root filesystem | 35 MiB | 28 GiB (with the toolchain) |
| `qosp` running `interactive_desktop_gl` | +86 MiB RSS | — |

So about 2.6x less at idle, which is much smaller than the disk difference.
An idle Linux is mostly kernel: at boot, before any process runs, 55 MiB is
already gone. What the image removes is systemd, journald, resolved,
networkd and unattended-upgrades (about 25 MiB of processes), the slab those
services keep alive, and nearly all of the page cache. It runs fine in 1 GiB. Most of
`qosp`'s own 86 MiB is Mesa's software rasterizer (`softpipe`) and its
threads. On a Pi, v3d does that work in hardware.

Two things that number depends on:

- **The buddy allocator used to write into the whole plugin window.**
  `buddy_reserve_range` fenced off the 1 GiB window one 64 KiB unit at a
  time, writing a free-list node into each unit: 16,384 writes into memory
  nobody had used. That made every `qosp` process 256 MiB resident on 16 KiB
  pages (macOS), and on this image the whole GiB, so a 1 GiB machine
  OOM-killed the application before it drew anything. It now takes the range
  as whole aligned blocks and writes nothing inside it (`runtime/buddy.c`).
- **Transparent huge pages.** This kernel defaults THP to `always`, which
  rounds every first write in the arena up to a 2 MiB page: the same
  application is 224 MiB with it on and 86 MiB with it off. Ubuntu's default
  is `madvise`. `CONFIG_TRANSPARENT_HUGEPAGE_MADVISE=y` in the kernel
  fragment (or `transparent_hugepage=madvise` on the command line) would
  make it the image's default too.

## What it costs in speed

The same five `.qa` apps (identical machine code; only the arena base differs
on macOS) run under each OS's qosp with `FPR_HARTS=4`, best of three, on one
Apple M4. The three guests each get 4 vCPUs under HVF.

| app | macOS (native) | FreeBSD 14.5 | Ubuntu 24.04 | Buildroot | Buildroot, THP `madvise` |
| --- | --- | --- | --- | --- | --- |
| `bfib`: fib 40, one actor | 1.19 s | 1.10 s | 1.16 s | 1.18 s | 1.12 s |
| `balloc`: 2000 × 40k conses, pool reset per round | 1.00 s | 0.96 s | 1.02 s | 1.27 s | 0.98 s |
| `bpar`: fib 39 on each of 4 harts | 0.84 s | 0.75 s | 0.86 s | 0.87 s | 0.75 s |
| `fanin`: 40 senders through one hub | 0.42 s | 0.49 s | 0.52 s | 0.56 s | 0.57 s |
| `pingpong`: 20k cross-hart round trips with sleeps | 7.90 s | 8.21 s | 9.02 s | 9.59 s | 9.48 s |

Compute and allocation are the same everywhere to within about 10%, which is
what you'd expect: once the app is running it is the same code on the same
cores, and the OS is not involved. Where the OS is involved, it shows:

- **Transparent huge pages cost Buildroot 27% on allocation.** Every pool
  reset hands pages back and the next round faults them in again, and with THP
  at `always` each fault zeroes 2 MiB. At `madvise` (Ubuntu's default) it is
  level with the rest. That is the second reason, after memory, to set
  `CONFIG_TRANSPARENT_HUGEPAGE_MADVISE=y` in the image's kernel.
- **Cross-hart wakes and short sleeps are slower on Linux.** `pingpong` is
  14% slower on Ubuntu and 20% slower on Buildroot than on macOS, with FreeBSD
  in between (4%). THP makes no difference there. It has not been
  investigated; timer slack and the two kernels' configs are the first
  suspects.

Caveats: the guests run under a hypervisor with 4 vCPUs that macOS may place
on efficiency cores, and each number is one app, not a workload.
