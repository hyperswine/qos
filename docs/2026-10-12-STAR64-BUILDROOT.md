# STAR64 Buildroot bring-up

Kind: build and validation record. Date: 2026-10-12.
Applicable source: QOS `a617193` plus the uncommitted STAR64 files recorded here.

Later on the same day, the [first-boot access update](2026-10-12-STAR64-FIRST-BOOT.md)
added public-key SSH and HDMI keyboard login. The image hash and access limits
below describe the first image. Its images and validation logs are now archived
under `.qos/star64/initial-images/` and `.qos/star64/first-image-validation/`;
the current `images/` and check logs describe the updated image.

The first STAR64 Linux image built successfully in the existing ARM64 Linux VM
and was written to the attached SD card, readback verified and safely ejected.
The image boots its RV64 kernel and userspace under QEMU `virt`, obtains an IPv4
DHCP lease, starts OpenSSH, and passes an offscreen EGL/GLES pixel readback using
Mesa softpipe. Physical STAR64 boot and peripherals remain untested.

## Configuration and artifacts

The new `tools/buildroot/br.sh star64` target uses Buildroot 2026.08, glibc,
RV64GC/LP64D and GCC 14.4.0. It preserves the pinned STAR64 vendor Linux 5.15.131
and U-Boot sources from Buildroot's earlier board port, with OpenSBI 1.6. The
bootloader patches fix integer MMIO pointer conversions with GCC 14 and pass
the detected DDR size to Linux through the extlinux boot path. The original
Pi 4 and QEMU targets retain their existing defaults.

Installed components include OpenSSH, dual Ethernet DHCP configuration,
RTL8852BU Wi-Fi driver and embedded firmware, wireless tools, the vendor HDMI
and display drivers, USB input, libdrm diagnostics, Mesa software EGL/GLES and
`star64-egl-check`. Remote login authentication and Wi-Fi network configuration
must be provisioned locally. QOS/FP-RISC applications and accelerated PowerVR
userspace are not included.

Local artifacts are under `.qos/star64/` (ignored build output):

- `images/sdcard.img`: 544,108,544 bytes.
- `images/rootfs.ext4`: 512 MiB root filesystem.
- `build.log`, `build-attempt-1.log`, `.config`: build evidence.
- `image-check.log`, `qemu-check.log`: validation evidence.
- `flash-card.log`: successful SD write, full readback and eject evidence.
- `flash-card-attempt-1.log`, `flash-card-attempt-2.log`: macOS access failures before the successful Terminal write.

The SD image SHA-256 is:

```text
090e9d02386a8c2b39197c738c1cff3c0eff958035882e43ec28aecbd7ab36c3
```

## Executed validation

`star64-image-check.py` passed for both GPT headers and partition-table CRCs,
firmware offsets, embedded firmware/rootfs bytes, the fixed root partition UUID
and ext4 compatibility flags. The same check passed in the build VM and on the
copied macOS artifacts.

`star64-qemu-check.py` passed with QEMU 11.1.2, using a temporary rootfs snapshot:

```text
EGL 1.5 vendor=Mesa Project
GL vendor=Mesa renderer=softpipe version=OpenGL ES 3.1 Mesa 26.1.8
pixel=64,128,191,255 GL-error=0x0 result=PASS
inet 10.0.2.15/24 brd 10.0.2.255 scope global eth0
STAR64_CHECK_PASS
```

The guest also passed `uname -m = riscv64` and `sshd -t`, and shut down cleanly.
The check connected to the guest's SSH server through a loopback QEMU forwarded
port and verified its OpenSSH protocol identification. Authenticated SSH login
remains untested because login material has not been provisioned.
The emulator exposes one Ethernet interface and no RTL8852BU USB device, so
startup reports missing `eth1`/`wlan0`; these are expected in this emulation.
The emulator uses its own firmware and device tree, so this does not validate
the STAR64 SPL, DDR initialization, U-Boot boot path, onboard Ethernet, Wi-Fi,
HDMI or input. The EGL result proves the tested software path only.

The final Buildroot invocation returned 0. The first attempt exposed old
U-Boot MMIO integer conversions rejected by GCC 14; the targeted patch was
applied and U-Boot rebuilt before the successful image build. Shell syntax and
tracked diff whitespace checks also passed.

## Physical bring-up

The attached card was identified as external removable `/dev/disk12`,
393,870,311,424 bytes, Generic Mass-Storage Media over USB. The prepared writer
rechecks the whole-disk identity, connection, capacity and image checksum before
unmounting and writing, then compares a full image-length readback and ejects.
macOS accepted administrator authentication but blocked the initial Python
script in Documents. Retrying from a temporary folder passed the image and
device identity checks and unmounted the card, but macOS denied opening the
raw SD device. Neither attempt wrote card data. A visible Terminal writer was
then opened to allow the normal macOS access and authentication prompts.
That writer completed successfully: 544,108,544 bytes written in 30.83 seconds,
full image-length readback SHA-256 matched the image above, and `/dev/disk12`
was safely ejected. The temporary image copy was removed after preserving logs.
The filesystem remains 512 MiB; the remainder of the physical card has not been
allocated to this image.

See [the board README](../tools/buildroot/board/qosp/star64/README.md) for build
commands and peripheral checks. Select SD boot and connect a serial console
at 115200 baud. Serial login is `root` with an empty password. Hardware boot,
Ethernet, Wi-Fi, HDMI and input require separate board validation. The old vendor
kernel is a bring-up baseline; kernel maintenance and PowerVR acceleration are
further work.
