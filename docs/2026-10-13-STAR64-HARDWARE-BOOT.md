# STAR64 hardware boot confirmed

Kind: physical-board validation record. Date: 2026-10-13.
This follows the [boot diagnosis](2026-10-12-STAR64-BOOT-DIAGNOSIS.md).

Follow-up: [native Linux and experimental FP-RISC execution tests](2026-10-13-STAR64-RUNTIME-TESTS.md)
record memory usage, bounded hardware checks, and 27 passing FP-RISC runs.

The STAR64 successfully booted the corrected Buildroot Linux image using a
**256 GB microSD Express card flashed through a UGREEN reader**. The user
reported a working HDMI display, local root login without a password, and
Ethernet connectivity. Authenticated SSH to the physical board also succeeded.
This image contains Linux and diagnostics, not QOS Portable applications.

## Card and reader comparison

| Combination | Observed result |
| --- | --- |
| Previous SanDisk 400 GB SD card and previous reader | Initial board trial showed no HDMI output or router lease. Subsequent host reads repeatedly failed at byte 4,194,304 and the device disconnected/reappeared. Changing USB ports did not resolve it. Rewriting the corrected image completed, but readback failed. |
| New 256 GB microSD Express card and UGREEN reader | Full image write completed in 6.21 seconds. The entire 544,104,448-byte readback matched the image SHA-256, and the card was safely ejected. The subsequent physical board boot worked. |

The exact failure in the previous card/reader combination remains unknown.
Both card and reader were replaced; the firmware was also corrected during
bring-up. These observations do not isolate the old card from its reader,
establish a general SanDisk incompatibility, or prove that microSD Express
is required. They record one failed combination and one working combination.

The successful image SHA-256 is:

```text
94b1ef9b033eab5e1a2a82557034ae2ecdf10405ef4c5c85b4aa347d98f04d09
```

## Executed checks over SSH

The Mac's existing ED25519 identity authenticated as root without an SSH
password. The device-tree model was `Pine64 Star64`, hostname `qos-star64`,
running RISC-V Linux `5.15.131`. The observed address was **192.168.0.151**:

```sh
ssh -i ~/.ssh/id_ed25519 root@192.168.0.151
```

- `eth1` was up at `192.168.0.151/24`, with a default route through
  `192.168.0.1`. `ethtool` reported 1000 Mb/s, full duplex and link detected.
- `eth0` retained `192.168.0.150/24` but was link down. This check validates
  the active `eth1` connection, not both physical Ethernet ports.
- Linux reported `MemTotal: 3961604 kB`, about 3.78 GiB usable RAM.
- `/dev/fb0` and `/dev/dri/card0` existed. The DRM connector
  `card0-HDMI-A-1` reported `connected`; visible display and local login
  operation were confirmed by the user.
- `star64-egl-check` passed on the board: Mesa 26.1.8, EGL 1.5, OpenGL ES 3.1,
  renderer `softpipe`, pixel `64,128,191,255`, GL error `0x0`. This establishes
  software rendering, not PowerVR acceleration.
- `wlan0` existed, but Wi-Fi association and traffic were not tested.

## Remaining boot-log findings

The successful login and network checks do not establish an error-free boot.
The saved kernel log includes initramfs unpacking failure, early L2-cache
`DataError`/`DataFail` messages, SPI-NOR probe failure, a thermal read timeout,
missing regulatory database, and early display-probe messages before the
framebuffer initialized. These remain recorded for investigation; their causes
and significance were not established in this check.

PowerVR GPU, video-decoder and Bluetooth firmware loads also failed. The image
does not include accelerated PowerVR userspace/firmware, and the passing EGL
check used software rendering. Bluetooth and video decoding are unvalidated.

The kernel reports that the backup GPT is at the image's end rather than the
256 GB card's physical end. The image checker verified both GPT CRCs and their
locations within the 544 MB image. No partition expansion or GPT relocation
was performed on the running board.

Local evidence is preserved under `.qos/star64/2026-10-13-new-card/`:
`flash-card.log`, `result.json`, `board-check.log`, and `dmesg.log`.
