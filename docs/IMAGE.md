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
