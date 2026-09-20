# A Linux image that exists to run one QOS Portable application

This is a Buildroot external tree. It builds a Linux system with nothing in
it but what QOS Portable needs — a kernel, Mesa, ssh, wifi, and `qosp` — so
that a Raspberry Pi 4 boots straight into an FP-RISC application, full screen,
with no desktop, no compositor and no window system anywhere in the picture.

    qos/tools/buildroot/
      configs/qosp_qemu_aarch64_defconfig   the test loop: QEMU virt
      configs/qosp_rpi4_defconfig           the target: a Pi 4 SD card
      package/qosp/                         the package that builds qosp
      board/qosp/                           kernel fragment, Pi config.txt
      br.sh                                 build
      boot.sh                               boot the QEMU image
      qosp-check.py                         boot it and assert what came up

## Why this is small

`qosp`'s graphics tier (`hal/unix/gfx.c`) was written for exactly this case.
It takes an EGL context on the **surfaceless** platform, renders an ES 3.1
scene into an offscreen FBO, and `drm_scanout.h` puts the frame on the monitor
through a KMS dumb buffer: one `SetCrtc` on the first `/dev/dri/card*` that
has a connected connector.

So the entire display stack is `libEGL` + `libGLESv2` + a DRM device. No X,
no Wayland, no GBM surface, no compositor, no display manager. That is the
whole reason an image like this can be a few tens of megabytes.

Input is the same story: `evdev_raw.c` reads `/dev/input/event*` and
`mice_raw.c` reads `/dev/input/mice`, both of which a bare Linux console has.

## Building

Buildroot does not run on macOS, so build on Linux. This repo already keeps a
VM for that:

    tools/arm64-vm/vm.sh up
    tools/arm64-vm/vm.sh sync

Inside it, once:

    git clone --depth 1 -b 2025.02.x \
      https://gitlab.com/buildroot.org/buildroot.git ~/buildroot

An image hosts **one** application, and which one is the point of the image,
so build that first — `br.sh` deliberately will not guess:

    make -C ~/qos qos-app PROG=programs/terra2.fpr    # writes qos/app.qa

Then:

    ~/qos/tools/buildroot/br.sh qemu        # or: rpi4

Output lands in `~/.cache/qosp-br/<target>/images`. Anything after the target
goes to Buildroot, so `br.sh qemu menuconfig` and `br.sh qemu qosp-rebuild`
work as usual.

### How `qosp` gets built

`qosp` is an FP-RISC program (`qos/portable/qosp.fpr`) whose HAL is the C
under `qos/hal/unix`, and the thing that knows how to assemble those is the
qos tree's own Makefile. So `package/qosp/qosp.mk` **calls that Makefile**
rather than restating its source list — the `portable-es` target, through two
hooks added for this:

| hook | what it does |
| --- | --- |
| `FPRBUILD_EXTRA=--cc <gcc>` | compile and link with Buildroot's cross compiler |
| `QOSP_ARCH=<arch>` | decide `-ffixed-x28` by the TARGET, not the build machine |
| `QOSP_ES_OUT=<path>` | write the binary into Buildroot's build dir |

`fpr` itself stays out of Buildroot: it is a Haskell program, it runs on the
build machine, and it only ever emits assembly for the target. Point
`BR2_PACKAGE_QOSP_FPRISC_DIR` at a checkout where `fpr` is already built
(empty means the sibling `../fprisc`, the rule the rest of the build follows).

**The build machine must have the target's architecture.** `fpr build --cc`
crosses to another *libc*, not to another *arch*: `Build.hs` still picks the
context switch, `-ffixed-x28` and `-no-pie` from the machine it runs on. An
aarch64 Linux box building an aarch64 image — which is what `tools/arm64-vm`
gives you — is sound; an x86_64 box would build the wrong thing, quietly.
This is written down in `fprisc/docs/BOUNDS.md`.

## Booting the QEMU image

From macOS, with the images copied out of the build VM:

    tools/buildroot/boot.sh pull     # rsync Image + rootfs.ext4 out of the VM
    tools/buildroot/boot.sh up       # headless, serial log
    tools/buildroot/boot.sh gui      # ... in a window you can watch

`qosp-check.py` does the whole thing unattended: boots the image, logs in over
the serial console, and asserts that the DRM device is there, that EGL came up
surfaceless, that the scanout engaged and that a frame was drawn.

## The Pi 4

`board/qosp/rpi4/config.txt` carries the one line that matters:

    dtoverlay=vc4-kms-v3d

That is what hands the display to the open vc4 KMS driver, so Linux exposes a
`/dev/dri/card*` **with a connector** — which is what the scanout probes for.
Without it the Pi has a framebuffer and no DRM device, and `qosp` renders
offscreen into nothing anyone can see. Mesa's `v3d` (3D) and `vc4` (display)
gallium drivers are both selected; `v3d` is a render node with no connectors
and the scanout probe skips it by design.

The other Pi-specific decision is **how drivers get loaded**. The bcm2711
defconfig ships `vc4` and `v3d` as modules, which is right for a distribution
with udev and wrong here twice: device creation is devtmpfs, so nothing would
load them at all and the image would boot to no `/dev/dri`; and even with
`mdev` loading them it would be a race, because `S99qosp` starts the
application at boot and a display that appears a moment later is one the
scanout probe has already missed. So `board/qosp/rpi4/linux-kms.fragment`
builds them in, and the card is there before userspace is. `mdev` is enabled
as well, for everything that legitimately arrives later — the Broadcom wifi
module, and anything plugged in after boot.

`br.sh rpi4` writes `images/sdcard.img`, which is a whole card:

    # pick the right disk very carefully
    diskutil list
    diskutil unmountDisk /dev/diskN
    sudo dd if=sdcard.img of=/dev/rdiskN bs=4m status=progress
    diskutil eject /dev/diskN

## Logging in, ssh and wifi

The image ships OpenSSH, `wpa_supplicant` and `iw`, and configures **none** of
them — credentials are not something a repo should invent.

Root has an empty password, so the **serial console** logs in with `root` and
Enter. `sshd` refuses empty passwords, so before ssh works you must either set
a root password (`BR2_TARGET_GENERIC_ROOT_PASSWD` in `menuconfig`) or add a
public key through a rootfs overlay (`BR2_ROOTFS_OVERLAY`).

For wifi, write `/etc/wpa_supplicant.conf` on the target — `wpa_passphrase` is
in the image for that — and bring it up with `wpa_supplicant -B -i wlan0 -c
/etc/wpa_supplicant.conf && udhcpc -i wlan0`. The Pi's onboard Broadcom
firmware (`brcmfmac_sdio-firmware-rpi`) is already installed.

## The application at boot

`BR2_PACKAGE_QOSP_AUTOSTART` (default on) installs `/etc/init.d/S99qosp`,
which runs `/usr/bin/qosp-session` on tty1 — where the scanout puts its
frames. The serial console keeps its own getty, so there is always a shell to
debug from, and the application's own output goes to `/var/log/qosp.log`
rather than over the picture.

`qosp-session` holds the only policy: the app is `/usr/share/qosp/app.qa`, its
QLOG disk persists in `/var/lib/qosp`, and assets come from
`/usr/share/qosp/assets`. All three are overridable from the environment, so
the same script serves the appliance and a hand-run session.

### Filling the screen

Whether the picture fills the display is the **application's** choice, not the
image's. `glInit 0 0` means "the display's own mode": the scanout is probed
first, the FBO is created at exactly that resolution, and the frame is blitted
1:1 over the whole screen — the log says `frame fullscreen`. Any explicit size
is kept and blitted centred in the mode, and the log says `frame centered`.

So an application meant to be an appliance should ask for `0 0`. The demos in
`programs/` ask for fixed sizes, because they were written for a window.
