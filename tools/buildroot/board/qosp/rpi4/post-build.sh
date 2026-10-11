#!/bin/sh
# Buildroot's overlay rsync grants go+rX; restore private provisioning modes.
set -eu
target=$1
for path in etc/wpa_supplicant.conf etc/ssh/sshd_config root/.ssh/authorized_keys; do
    if [ -f "$target/$path" ]; then
        [ ! -L "$target/$path" ] || { echo "Pi provisioning file is a symlink: $path" >&2; exit 1; }
        chmod 0600 "$target/$path"
    fi
done
for path in root root/.ssh; do
    if [ -d "$target/$path" ]; then
        [ ! -L "$target/$path" ] || { echo "Pi provisioning directory is a symlink: $path" >&2; exit 1; }
        chmod 0700 "$target/$path"
    fi
done
# QOS owns tty1 when autostart is selected; the serial getty stays available.
if [ -n "${BR2_CONFIG:-}" ] && grep -q '^BR2_PACKAGE_QOSP_AUTOSTART=y$' "$BR2_CONFIG"; then
    sed -i '/^tty1::.*# HDMI console$/d' "$target/etc/inittab"
fi
