# STAR64 Linux bring-up

This target builds a RISC-V Linux SD-card image alongside the Pi 4 target.
The baseline defconfig keeps `BR2_PACKAGE_QOSP` optional. FP-RISC now supports
Linux RV64GC/LP64D, and QOS Portable Main runs on the physical STAR64 with
software EGL, HDMI scanout and USB keyboard input. See the
[October 14 build and hardware record](../../../../../docs/2026-10-14-STAR64-PORTABLE.md)
for cross-build commands, installation and remaining limits.

## Build

Use a Linux build machine. On this Mac, the existing ARM64 VM is suitable:

```sh
tools/arm64-vm/vm.sh up
```

Inside the VM, download and extract Buildroot 2026.08 into
`~/buildroot-2026.08`, then run from this checkout:

```sh
tools/buildroot/br.sh star64
```

To personalize SSH access, provide an OpenSSH public-key file on the Linux
build machine. Keep this input outside the tracked overlay:

```sh
QOSP_STAR64_AUTHORIZED_KEYS=/path/to/authorized_keys tools/buildroot/br.sh star64
```

The post-build hook installs it as root's `authorized_keys`, with the directory
mode 0700 and file mode 0600. It accepts plain public-key lines without key
options. Without this variable, it removes any previously installed key from
the output tree, so unpersonalized rebuilds do not retain earlier access.

`BUILDROOT` overrides the source directory; `QOSP_BR_O` overrides the output
parent. The default image is `~/.cache/qosp-br/star64/images/sdcard.img`.
`br.sh` preserves an existing output `.config`; explicitly reapply
`qosp_star64_defconfig` when changing the tracked defaults.

Before flashing, check the assembled image and boot its Linux userspace
under QEMU (install `qemu-system-riscv64` on the machine running the check):

```sh
python3 tools/buildroot/star64-image-check.py ~/.cache/qosp-br/star64/images
python3 tools/buildroot/star64-qemu-check.py ~/.cache/qosp-br/star64/images \
    --log /tmp/star64-qemu.log
```

For a personalized image, also exercise SSH authentication and the virtual
console using QEMU's emulated USB keyboard:

```sh
python3 tools/buildroot/star64-qemu-check.py ~/.cache/qosp-br/star64/images \
    --ssh-identity ~/.ssh/id_ed25519 --console-login --log /tmp/star64-qemu.log
```

The host SSH client uses the identity locally. The checker does not copy it
into the guest, and uses a temporary known-hosts file for the emulator.

The first checks both GPT CRCs, firmware offsets, root partition UUID,
all embedded component bytes, the SPL ROM header/CRC, the OpenSBI payload
offset and U-Boot's automatic SD boot environment. The second uses a temporary disk snapshot
and checks RV64 Linux boot, offscreen software EGL, the SSH protocol listener
and configuration, and DHCP on emulated Ethernet. The optional checks require
a successful authenticated SSH command and a command typed after logging in
on `tty1` through the emulated USB keyboard. QEMU's `virt` machine does not emulate STAR64's
boot ROM, DDR initialization, real network controllers, Wi-Fi or HDMI.

The target uses glibc, RV64GC/LP64D, GCC 14, and Buildroot 2026.08 userspace.
The kernel and bootloader are the pinned Fishwaldo STAR64 revisions from
Buildroot 2025.02's board port, with OpenSBI 1.6. This deliberately retains
the vendor HDMI/display and RTL8852BU drivers. It is an initial hardware
bring-up baseline with an old vendor kernel, not a maintained deployment
image. Updating that kernel remains work to do.

The GPT image contains the vendor SPL at 2 MiB, the OpenSBI/U-Boot FIT at
4 MiB, and a 512 MiB ext4 root filesystem. A fixed root partition UUID
avoids depending on the SD card's Linux MMC enumeration. U-Boot and Linux
both use STAR64 board configuration, rather than a VisionFive 2 image.
The U-Boot board setup hook updates the kernel device tree with its detected
DDR range when booting through extlinux, instead of retaining the vendor
DTB's fixed 4 GiB memory node.

U-Boot scans SD (`mmc1`) before eMMC (`mmc0`) and boots the extlinux file on
the ext4 root partition. It uses its compiled environment, so saved SPI
environment settings cannot override this card's boot command. A firmware
video initialization error is reported without stopping boot; Linux still
initializes its own display driver. These changes address defects found after
the first physical trial; see the [boot diagnosis](../../../../../docs/2026-10-12-STAR64-BOOT-DIAGNOSIS.md).

## First boot

Select SD boot on the STAR64 and connect an HDMI display and USB keyboard.
The image starts a text login on `tty1`; use `root` with an empty password.
The serial login remains available at 115200 baud for recovery. This is a text
console, not a graphical desktop. HDMI text login worked in the
[physical board trial](../../../../../docs/2026-10-13-STAR64-HARDWARE-BOOT.md)
using a microSD Express card flashed through a UGREEN reader.

Both `eth0` and `eth1` attempt DHCP with bounded initial attempts and background
retries. OpenSSH starts automatically and permits public-key authentication only.
For an image personalized as above, find the board's address in your router's
DHCP leases (hostname `qos-star64`) or with `ip -br addr` on its local console,
then connect from the Mac with `ssh root@<board-ip>`. A public key must be
provisioned for remote login. No private key or Wi-Fi access material is included
in the tracked image configuration.

Onboard Wi-Fi uses the vendor `8852bu` module, whose firmware is embedded
in the driver. Configure `/etc/wpa_supplicant.conf` locally, then start
`/etc/init.d/S41wifi start`. Check the interface name with `iw dev` if
`wlan0` does not appear. Pi Broadcom module settings are not copied here.

## Validation on the board

```sh
uname -a
ip -br addr
ethtool eth0
ethtool eth1
lsusb
iw dev
ls -l /dev/dri /dev/input
modetest -c
star64-egl-check
```

`star64-egl-check` creates an ES3 context on the surfaceless EGL display
platform, clears an offscreen buffer and checks a pixel readback. It prints
the actual renderer and GL version. The initial Mesa driver is **softpipe**,
so a passing result establishes software rendering only, not GPU
acceleration, GLES 3.1 compatibility, HDMI scanout, or QOS application support.
Use `modetest` separately to inspect display connectors and modes.

Accelerated PowerVR EGL/GLES requires matching vendor userspace libraries,
GPU firmware, and the kernel driver. Those are not supplied by this target.
The optional `tools/buildroot/star64-powervr.py` bundle has now passed physical
EGL/GLES and QOS Main checks with this kernel's DDK 1.17.6210866. See the
[hardware rendering record](../../../../../docs/2026-10-14-STAR64-POWERVR.md)
for matching versions, installation and recovery. The baseline SD image still
uses software Mesa.
Physical boot, HDMI text login, one gigabit Ethernet port, authenticated SSH
and software EGL passed the October 13 board trial. Wi-Fi, the second Ethernet
port and other peripherals still need physical validation.
An image build or QEMU userspace check cannot establish those hardware results.

## References

- [Buildroot 2026.08](https://buildroot.org/downloads/buildroot-2026.08.tar.xz)
- [Original STAR64 kernel revision](https://github.com/Fishwaldo/Star64_linux/tree/1456c984f15e21e28fb8a9ce96d0ca10e61a71c4)
- [Original STAR64 U-Boot revision](https://github.com/Fishwaldo/u-boot/tree/172b47f62039605d6806fa96bd403c21cda28996)
- [PINE64 STAR64 documentation](https://pine64.org/documentation/STAR64/_full/)
