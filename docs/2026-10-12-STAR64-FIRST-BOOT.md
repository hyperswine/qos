# STAR64 first-boot access

Kind: implementation and validation record. Date: 2026-10-12.
Applicable source: QOS `a617193` plus the uncommitted STAR64 Buildroot changes.
This updates the [initial image](2026-10-12-STAR64-BUILDROOT.md).

The subsequent board trial produced no HDMI output or visible DHCP lease.
The [boot diagnosis and corrected firmware](2026-10-12-STAR64-BOOT-DIAGNOSIS.md)
supersede the image and artifact locations recorded below.

The image now starts an HDMI text login on `tty1` alongside the serial login,
and accepts root SSH login using the Mac's standard public ED25519 key. Connect
an HDMI monitor, USB keyboard and Ethernet cable, select SD boot, and power on.
At the local text console, log in as `root` with an empty password. Serial is
available as a recovery path, rather than a required setup step.

Both Ethernet ports attempt DHCP automatically. Find the address in the router's
DHCP leases under hostname `qos-star64`, or run `ip -br addr` at the local console.
From the Mac:

```sh
ssh -i ~/.ssh/id_ed25519 root@<board-ip>
```

SSH requires public-key authentication. Password and keyboard-interactive SSH
authentication are disabled. The private key stays on the Mac; only the public
key is installed into the image. The tracked overlay contains no personal key.
The Linux build uses the ignored local input selected through
`QOSP_STAR64_AUTHORIZED_KEYS`. The post-build hook installs root's `.ssh`
directory with mode 0700 and `authorized_keys` with mode 0600. An unpersonalized
rebuild removes the earlier installed key instead of retaining access silently.

The kernel already enabled the STAR64 HDMI driver, framebuffer console and USB
HID. The board device tree enables HDMI, and the vendor display driver calls
`drm_fbdev_generic_setup`. The updated kernel also enables generic PCI-host and
virtio GPU support to test the local console with emulated USB input.

## Executed validation

The rebuild returned 0. The GPT/component/ext4 checks passed for the copied
image. QEMU checks passed on the actual rebuilt RISC-V kernel and userspace:

- An SSH command authenticated with the existing Mac identity and returned
  `STAR64_SSH_AUTH_PASS`. Temporary emulator host keys were isolated from the
  Mac's normal known-hosts file.
- QMP injected `root` and a command through an emulated USB keyboard. The
  command created a marker from the `tty1` login session; the guest confirmed
  the keyboard was registered and returned `STAR64_USB_CONSOLE_PASS`.
- Root ownership and exact public-key directory/file modes passed.
- Ethernet DHCP, SSH configuration, software EGL pixel readback and orderly
  shutdown passed again; the guest returned `STAR64_CHECK_PASS`.

The image remains 544,108,544 bytes, with a 512 MiB root filesystem. SHA-256:

```text
efe011d830117e283b217d29113154b2af05f5bf4c7f60b447ec1c40153ff2c9
```

Current local artifacts and logs are under `.qos/star64/`:
`images/sdcard.img`, `image-check.log`, `qemu-check.log`, and
`build-console-login.log`. The first image and its successful validation logs
were preserved under `initial-images/` and `first-image-validation/`.

## SD-card write

The removable card was reidentified as `/dev/disk12`, 393,870,311,424 bytes. Its
USB connection changed since the first write, so the writer's expected path was
updated from the fresh device information before launching. It rechecks the
whole external/removable disk identity, capacity, USB path and image hash before
writing, then compares the full image-length readback and ejects the card.

The Terminal writer completed successfully: 544,108,544 bytes written in 34.96
seconds. The full image-length readback matched the SHA-256 above, and the card
was safely ejected. The successful log is `.qos/star64/flash-card.log`; the
temporary image copy and writer directory were removed after saving evidence.

## Remaining hardware checks

The emulator validates the login and keyboard path using its own display and
USB devices. It does not establish physical STAR64 boot, HDMI scanout, keyboard
operation on the board's USB controller, or either real Ethernet port. Those
still require a board trial. The image provides a text console and software
Mesa EGL; it does not include a graphical desktop, accelerated PowerVR userspace
or QOS/FP-RISC applications.

See [the board README](../tools/buildroot/board/qosp/star64/README.md) for rebuilding
and the peripheral checks.
