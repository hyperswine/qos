# Quiet QOS boot on Raspberry Pi 4

Kind: implementation and validation record. Updated 2026-10-14.
Applies to the Pi 4 Buildroot image and the installed Pi, not STAR64.

## Boot sequence

The firmware rainbow is disabled with `disable_splash=1`. The kernel command
line retains the root device, `rootwait` and the UART console, removes the
HDMI `console=tty1`, and adds:

```
quiet loglevel=3 logo.nologo vt.global_cursor_default=0 consoleblank=0
```

`S12qosp-splash` draws a centered QOS wordmark into `/dev/fb0`, after the S10
device/module coldplug and before networking and QOS start. It waits at most
five seconds for the framebuffer and continues
boot if the display is absent or unsupported. The helper supports packed
true-color RGB565, 24-bit and 32-bit framebuffers, including padded rows and
pan offsets. It exits after drawing: there is no resident splash daemon.

The authoritative asset is [`assets/qos-boot-logo.svg`](../assets/qos-boot-logo.svg).
It uses circles and rounded polylines, with white lettering and a cyan Q tail.
`python3 tools/boot-logo.py` regenerates the small C geometry header. The device
rasterizes those vectors at its actual display resolution, without SVG, font
or image-decoding libraries.

With `FPR_BOOT_SPLASH=1`, QOS seeds its first KMS framebuffer with the same logo
before enabling scanout. The GUI replaces it when it draws its first frame.
`/etc/default/qosp` exports this setting. The splash keeps tty1 in graphics mode
to prevent console text from overwriting the picture.

This is an early Linux userspace splash. There can still be a black interval
during firmware/kernel startup, before a Linux framebuffer exists. Connect and
power the display before booting. The existing graphics host initializes its
scanout once; a session started with no display needs restarting after a display
is connected.

## Build and recovery

`qosp_rpi4_defconfig` enables `BR2_PACKAGE_QOSP_BOOT_SPLASH`. Other board
defconfigs leave it disabled. This optional package setting requires QOS
autostart. The Pi post-build hook refuses a quiet image when the splash helper
or init script was not installed.

UART boot messages and the serial login remain available. Ctrl+Alt+F2 offers a
USB keyboard recovery login; normal QOS startup owns tty1. SSH remains enabled.
The logs are `/var/log/qosp-splash.log` and `/var/log/qosp.log`.

When changing firmware `config.txt` in an existing Buildroot output tree, run
`rpi-firmware-reinstall` before the final image build so the copied firmware
configuration is refreshed. Rebuild the QOS package after changing the logo or
scanout header; a top-level image build alone does not invalidate its stamps.
Keep host, Main and all plugins on the same ABI and compiler revision.

The installed Pi's original host, service library and inittab are saved in
`/root/qosp-before-splash-20261014/root.tar`; original FAT `cmdline.txt` and
`config.txt` are alongside it. To undo the installed changes over SSH, stop
`S99qosp`, restore that archive, remove `S12qosp-splash`, restore the two boot
files to `/dev/mmcblk0p1` mounted as FAT, restore the saved `qosp-default` if
present (otherwise remove the tagged `QOSP_BOOT_SPLASH` line), sync and reboot.
The persistent `/var/lib/qosp/Main.disk` was not replaced.

## Validation

`python3 tools/buildroot/splash-check.py` checks generated geometry, centering,
colors, guarded and padded pixel buffers, portrait/small/odd display sizes,
quiet command-line policy, UART/root preservation, the recovery login,
idempotent builds and refusal when the helper is missing. The check is included
in `check-all.sh`. Linux's scanout pixel checks also pass for RGB orientation,
pitch, native placement, aspect fit and display fill.

The AArch64 QEMU boot displayed the early logo at 1280x800, byte-for-byte
identical to the host renderer's PPM, then displayed Main and stopped cleanly.
A disposable image copy contained a three-second init delay to capture the
early stage deterministically; production images contain no added delay.
The test also passed after rebuilding with compiler revision 41 and the Pi's
actual Main/plugin snapshot. The Pi SD image and QEMU rootfs were rebuilt with
that same revision. The local Pi image is `.qos/splash/rpi4/sdcard.img`, with
SHA-256 `e49dfc6776d516279bc10053c6948e2221a4dca54564b08a4be4cb2b27a4e6b6`.
It is a private local image containing this Pi's provisioned settings and a
consistent copy of its application disk, not a public redistributable artifact.

The physical Pi was authenticated at `192.168.0.233` using its existing saved
SSH identity. It is a Pi 4 Model B Rev 1.4. An initial deployment used a legacy
compiler-38 host while its actual installed Main required 19.41; the loader
refused it safely. The original compatible host was restored, then a new
splash-enabled AArch64 host was built with compiler revision 41 and installed.
Main and its clock/logs/browser/disk plugins then reached readiness with V3D
EGL. The application disk checksum matched across each host replacement.
After another reboot, boot ID `846eb08d-4b15-432e-a5e9-a3674fde77cd` was new,
Main automatically reached readiness, the quiet kernel flags were active,
and SSH was reachable again at `.233`. The deployed host checksum is
`d4676ae31a4829323f55847dbc8d6f0e96cd8815fadcf784dda3976750a7ac2d`.

The display was disconnected during the first remote reboot validation. Therefore
physical splash appearance, lack of visible boot text and the display handoff
still require a connected-display boot check; headless startup cannot prove
them. No STAR64 runtime or boot configuration was changed.

## Follow-up: early splash timing and Pi bootloader display

The user subsequently observed a Pi boot screen, repeated black transitions,
then a very brief QOS logo immediately before Main. With HDMI-A-2 connected,
the log still reported that `/dev/fb0` was unavailable. The original S02 helper
ran before S10mdev: its five-second wait delayed device coldplug, so the display
driver could not load until after that wait expired. Only QOS's later KMS
buffer seed displayed the wordmark. Moving the helper to S12 fixes this ordering.
Incremental package installation removes the obsolete S02 name.

On the installed Pi, an executable `S41wifi.before-bounded-stop` backup was also
matched by rcS's `S??*` glob and run as another Wi-Fi service. It was preserved
outside `/etc/init.d`, in `/root/qosp-before-splash-timing-20261014`, to avoid
the duplicate startup and shutdown. That directory also holds the previous
splash helper, S02 script and firmware config for timing-change recovery.

`disable_fw_kms_setup=1` lets Linux select the monitor's mode from EDID, rather
than inheriting the firmware's fallback `video=HDMI-A-1:720x576M@50` argument.
See [the official config.txt documentation](https://www.raspberrypi.com/documentation/computers/config_txt.html#disable_fw_kms_setup).
This does not promise an uninterrupted signal across firmware and kernel
display initialization; visual transition testing is still needed.

After the corrected physical reboot (boot ID
`e3ff24c5-938c-4a29-8f04-7b7b1bf00159`), the splash log recorded start at 3.85
seconds and successful drawing on the 1024x600 16-bit framebuffer. Reading
back `/dev/fb0` matched all 614,400 expected RGB565 pixels exactly. The old
firmware video argument was absent, Main and its plugins reached readiness,
and SSH returned at `.233`. QEMU also passed with the S12 helper, an exact
early-logo pixel match, GUI display and clean shutdown. The disposable capture
delay now runs at S13, after the real splash; it is absent from production.

The current local SD image supersedes the earlier checksum above:
`faf13d7a50639f2e79fb5d28a312af0a7d2cbd810ed47578c4753a89027bf12f`.

The separate Pi bootloader diagnostics screen is controlled by EEPROM
`DISABLE_HDMI=1`, not `disable_splash` in config.txt. The official
[bootloader configuration documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#disable_hdmi)
describes that setting. A configuration-only update and rollback image were
prepared from the exact installed release, version
`57db150d63864d47e6c9071f6b086a5401eb4e92`, build timestamp `1762363706`.
The official source image was pinned to rpi-eeprom repository commit
`32f795a171b0e08e9356e4a685481a5a2c0b4508`,
`firmware-2711/latest/pieeprom-2025-11-05.bin`.
Existing settings and boot order are preserved, and comparison of all other
image sections confirmed they were unchanged. The prepared update SHA-256 is
`fa019c8a9f866144693c39c6a00e4267353bf956300d1123699e1fd21c5a1d5a`.

Automatic approval review initially rejected applying the persistent firmware
change without explicit user approval. The user then explicitly approved it.
The configuration-only update was applied and the Pi rebooted successfully
(boot ID `b6e2b26b-0653-4b3e-80fb-02b356e7031b`). Reading its bootloader nvmem
configuration matched the approved file exactly: `DISABLE_HDMI=1` is active,
`BOOT_ORDER=0xf14` and firmware version `57db150d...` are unchanged.
The splash drew successfully at 3.83 seconds, and Main automatically reached
readiness again. Visual verification of the final transition remains pending;
the user was away from the display during this update.

Completed update files were saved under
`/root/qosp-before-eeprom-quiet-20261014` and removed from the boot partition
after verification. That directory holds the original config and rollback
image as well. A rollback must use a newly generated `.sig` timestamp so the
bootloader accepts it as a fresh configuration update. Local artifacts remain
under `.qos/splash/eeprom/`; ordinary Pi and QEMU SD/rootfs images contain no
EEPROM update files. This is a one-time board setting, separate from the SD
image's firmware `config.txt` and the Linux splash helper.
