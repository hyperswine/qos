# STAR64 SD boot diagnosis

Kind: investigation, implementation and validation record. Date: 2026-10-12.
Applicable source: QOS `a617193` plus the uncommitted STAR64 Buildroot changes.
This follows [first-boot access](2026-10-12-STAR64-FIRST-BOOT.md).

## Physical report

The personalized image produced no HDMI output and no visible router DHCP
lease with SD boot selected and HDMI/Ethernet connected. The user reported
one solid green LED and recalled either 4 or 8 GiB RAM. No serial trace is
available, so the exact physical stopping point remains unobserved.

The failed image was 544,108,544 bytes, SHA-256:

```text
efe011d830117e283b217d29113154b2af05f5bf4c7f60b447ec1c40153ff2c9
```

It was previously flashed with a matching full image-length readback. Its
components and logs are preserved locally under `.qos/star64/pre-boot-fix/`.
Rerunning its Linux QEMU check after the hardware report passed, including
authenticated SSH and USB-keyboard console login. This excludes neither
bootloader nor physical peripheral failures: the emulator loads Linux directly.

## Confirmed firmware defect

The pinned vendor U-Boot selects `devnum=1` for SD boot, and SPL selects
`BOOT_DEVICE_MMC2` for that switch setting. However, `BOOT_TARGET_DEVICES` in
`include/configs/pine64-star64.h` defined only `MMC 0` and DHCP. The compiled
environment therefore had `bootcmd_mmc0` but no `bootcmd_mmc1`. Its final
`distro_bootcmd` never scanned the SD controller for our extlinux configuration.
The earlier vendor command chain also assumed FAT/uEnv files absent from
this ext4 image.

Patch `0003-star64-scan-sd-mmc-before-emmc.patch` adds MMC 1 first, then MMC 0
and DHCP. The U-Boot fragment now sets `bootcmd=run distro_bootcmd` and
`CONFIG_ENV_IS_NOWHERE=y`, disabling the SPI environment backend. A saved
environment from an older installation cannot replace these compiled defaults.
This does not erase or replace SPI flash contents.

Patch `0004-star64-continue-boot-without-firmware-video.patch` also makes a
returned firmware video initialization error nonfatal. Previously,
`board_late_init()` returned that error into U-Boot's initialization sequence,
which can halt before Linux and Ethernet start. Whether this occurred on the
physical board is unknown. The patch handles returned errors; it cannot fix
a driver that hangs internally. Linux retains its own HDMI driver.

OpenSBI's payload places U-Boot at offset `0x200000`, corresponding to
`0x40200000` in RAM. SPL's FIT loader appends its embedded DTB when the FIT
has no separate FDT image. Both were checked against the actual build; no
change to OpenSBI placement or DTB handoff was justified by this investigation.

## Corrected build and checks

U-Boot and OpenSBI were rebuilt from clean package directories after reapplying
the tracked defconfig. The complete Buildroot run returned 0. The saved U-Boot
configuration confirms the new boot command and disabled SPI environment.

The image checker now verifies the SPL ROM header and CRC, OpenSBI's embedded
U-Boot offset, SD-first boot targets and the compiled boot command, in addition
to GPT CRCs, component bytes, partition offsets, root PARTUUID and ext4 flags.
It rejects the previous image for its missing SD boot target and accepts the
corrected image. This catches a defect that Linux-only QEMU testing bypasses.

The actual root filesystem's extlinux configuration refers to `/boot/Image`
and `/boot/jh7110-pine64-star64.dtb`. Both embedded files matched the separate
kernel and DTB artifacts. Its root argument is the expected fixed PARTUUID,
with `rootwait`, `console=tty1`, `console=ttyS0,115200` and `earlycon=sbi`.

QEMU passed on the corrected kernel/root filesystem:

- RV64 Linux boot and emulated Ethernet DHCP.
- Authenticated SSH with the Mac's existing identity and public-key-only server
  configuration; root's authorized-key ownership and modes.
- `tty1` root login and a command entered through an emulated USB keyboard.
- Software Mesa EGL/GLES rendering with pixel readback, and orderly shutdown.

QEMU uses its generic `virt` board, a temporary disk snapshot and direct Linux
boot. It does not execute STAR64's boot ROM, SPL, DDR initialization or U-Boot,
and does not validate the board's real HDMI, Ethernet, USB or Wi-Fi hardware.

The corrected image is 544,104,448 bytes, with the root partition starting at
byte 7,216,128 and occupying 512 MiB. SHA-256:

```text
94b1ef9b033eab5e1a2a82557034ae2ecdf10405ef4c5c85b4aa347d98f04d09
```

Local artifacts: `.qos/star64/images/`, `image-check.log`, `u-boot.config`,
`build-boot-fix.log`, and `qemu-boot-fix.log`.

## Returned card and next board trial

The returned card was reidentified as the same external removable 393,870,311,424-byte
device. Two read attempts failed at exactly byte 4,194,304, the start of the
U-Boot partition. Both recovered prefixes match the original image byte for
byte. The first used 4 MiB transfers; the retry used 512 KiB transfers. The
retry reported `Input/output error`, followed by `Device not configured` on
two further attempts. An intervening inspection also found the raw device
temporarily absent after unmount, although it reappeared afterward. The user
confirmed the card remained physically connected.

The guarded snapshot-and-write path stopped before any write. Changing USB
ports reproduced the same read failure at 4 MiB. After that failure, macOS
enumerated the card again as `/dev/disk13`, with the same capacity, partition
layout and reader identity at the new USB path. These failures establish an
unreliable read path, but do not distinguish the card from its adapter/reader.
They may be relevant to physical boot independently of the fixed bootloader
configuration.

Because the snapshot did not reach the root filesystem, it cannot establish
whether Linux ever mounted or changed it during the board trial. Preserved
local evidence is under `.qos/star64/pre-boot-fix/`: `card-prefix.img`,
`card-prefix-retry.img`, `card-prefix-other-port.img`, and the corresponding
`card-snapshot-*.log` files.

The card was already authorized for overwrite, and the original image exists
on the host. After preserving the partial inspection evidence, a direct rewrite
was attempted as a repair: rewriting flash may recover an unreadable region.
The reader disappeared again after an unmount, before any write. After freshly
identifying it again as `/dev/disk12`, the final writer checked every partition
was already unmounted and skipped the unnecessary unmount operation.

The replacement write transferred all 544,104,448 bytes in 102.74 seconds and
returned successfully, but the subsequent raw-device readback failed with
`OSError: [Errno 5] Input/output error`. It did not obtain a matching checksum.
The card has therefore been overwritten, but is **not verified or ready to
claim as bootable**. The writer and kernel/QEMU validation results must remain
separate. The failure log is `.qos/star64/flash-boot-fix-failed.log`; the earlier
successful flash log remains under `pre-boot-fix/flash-card.log`.
The writer exited after the failed verification; its preceding `sync` completed.
All partitions had been confirmed unmounted. A subsequent `diskutil eject`
reported `Volume failed to eject`, so safe ejection was not confirmed either.

A different card reader/adapter is the next useful test. If the same card
still fails through another reader, replace the card and flash the already
validated host image. Changing USB ports alone did not resolve this failure.

A physical boot trial remains necessary. If HDMI and DHCP
still fail, a 115200-baud serial boot trace is the next way to distinguish ROM,
SPL/DDR, U-Boot and kernel failures.
