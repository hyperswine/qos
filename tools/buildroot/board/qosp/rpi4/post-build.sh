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
    cp -p "$target/etc/inittab" "$target/etc/inittab.qosp"
    sed '/^tty1::.*# HDMI console$/d' "$target/etc/inittab" > "$target/etc/inittab.qosp"
    mv "$target/etc/inittab.qosp" "$target/etc/inittab"
    # A keyboard recovery login remains on Ctrl+Alt+F2, outside the boot VT.
    if ! grep -q '^tty2::' "$target/etc/inittab"; then
        printf '\ntty2::respawn:/sbin/getty -L tty2 0 linux # QOSP_RECOVERY_CONSOLE\n' >> "$target/etc/inittab"
    fi
fi

if [ -n "${BR2_CONFIG:-}" ] && grep -q '^BR2_PACKAGE_QOSP_BOOT_SPLASH=y$' "$BR2_CONFIG"; then
    [ -x "$target/usr/bin/qosp-splash" ] && [ -x "$target/etc/init.d/S12qosp-splash" ] || {
        echo "Pi splash selected but not installed; rebuild qosp before making the image" >&2; exit 1;
    }
    # The last kernel console is /dev/console: init's messages now go to UART,
    # while tty1 holds the splash/GUI. Keep the serial console and root flags.
    cmdline=${BINARIES_DIR:?}/rpi-firmware/cmdline.txt
    [ -f "$cmdline" ] || { echo "Pi firmware cmdline.txt missing" >&2; exit 1; }
    awk '{for (i=1;i<=NF;i++)
        if ($i !~ /^console=tty[0-9]+(,.*)?$/ &&
            $i !~ /^(quiet|loglevel=.*|logo.nologo|vt.global_cursor_default=.*|consoleblank=.*)$/)
            printf "%s ", $i;
    } END {print "quiet loglevel=3 logo.nologo vt.global_cursor_default=0 consoleblank=0"}' \
        "$cmdline" > "$cmdline.qosp"
    mv "$cmdline.qosp" "$cmdline"
    mkdir -p "$target/etc/default"
    touch "$target/etc/default/qosp"
    cp -p "$target/etc/default/qosp" "$target/etc/default/qosp.new"
    sed '/# QOSP_BOOT_SPLASH$/d' "$target/etc/default/qosp" > "$target/etc/default/qosp.new"
    printf 'export FPR_BOOT_SPLASH=1 # QOSP_BOOT_SPLASH\n' >> "$target/etc/default/qosp.new"
    mv "$target/etc/default/qosp.new" "$target/etc/default/qosp"
fi
