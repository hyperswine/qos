#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Keep HDMI/USB keyboard login alongside the serial recovery console.
if ! grep -q '^tty1::' "$TARGET_DIR/etc/inittab"; then
    printf '\ntty1::respawn:/sbin/getty -L tty1 0 linux # STAR64_HDMI_LOGIN\n' >> "$TARGET_DIR/etc/inittab"
fi

# Personalize locally; never put a user's key in the tracked rootfs overlay.
# Remove an earlier personalized key when rebuilding without this input.
if [ -n "${QOSP_STAR64_AUTHORIZED_KEYS:-}" ]; then
    [ -s "$QOSP_STAR64_AUTHORIZED_KEYS" ] || {
        echo "STAR64: QOSP_STAR64_AUTHORIZED_KEYS must name a nonempty public-key file" >&2
        exit 1
    }
    awk 'NF && $1 !~ /^#/ {
        if ($1 !~ /^(ssh-|ecdsa-|sk-)/ || NF < 2) exit 1;
        keys++
    } END { if (!keys) exit 1 }' "$QOSP_STAR64_AUTHORIZED_KEYS" || {
        echo "STAR64: expected OpenSSH public keys, without private key material or key options" >&2
        exit 1
    }
    install -d -m 0700 "$TARGET_DIR/root/.ssh"
    install -m 0600 "$QOSP_STAR64_AUTHORIZED_KEYS" "$TARGET_DIR/root/.ssh/authorized_keys"
else
    rm -f "$TARGET_DIR/root/.ssh/authorized_keys"
fi

"$HOST_DIR/bin/spl_tool" -c -f "$BINARIES_DIR/u-boot-spl.bin"
cp "$HERE/star64-uboot-fit-image.its" "$BINARIES_DIR/"
(cd "$BINARIES_DIR" && "$HOST_DIR/bin/mkimage" -f star64-uboot-fit-image.its \
    -A riscv -O u-boot -T firmware opensbi_uboot_payload.img)
