#!/bin/sh
# boot.sh -- boot the Buildroot QEMU image built by br.sh.
#
#   boot.sh pull        copy Image + rootfs.ext4 out of the build VM
#   boot.sh up          boot headless; the console goes to serial.log
#   boot.sh gui         boot in a window you can watch and type into
#   boot.sh down        stop it
#   boot.sh qemu-args   print the machine model, one argument per line
#
# The point of the QEMU target is that it exercises the SAME path a Pi
# does: virtio-gpu gives a /dev/dri/card0 with a connected connector, so
# drm_scanout.h takes it and presents through a dumb buffer exactly as
# vc4 would.  Only the gallium driver underneath differs (swrast here,
# v3d there).  qemu-xhci + usb-kbd + usb-mouse are there for the same
# reason: they arrive as real evdev and /dev/input/mice.
#
# `qemu-args` is that machine model written down once: qosp-check.py
# reads it and adds its own console and monitor sockets, so the thing
# the test boots cannot drift from the thing a person boots.
#
# State lives in $QOSP_RUN_DIR (default ~/.cache/qosp-br-run).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DIR=${QOSP_RUN_DIR:-$HOME/.cache/qosp-br-run}
VMDIR=${QOS_VM_DIR:-$HOME/.cache/qos-arm64-vm}
VMPORT=${QOS_VM_PORT:-2222}
PORT=${QOSP_SSH_PORT:-2223}
IMAGES=${QOSP_BR_IMAGES:-.cache/qosp-br/qemu/images}
SSHO="-i $VMDIR/id_vm -p $VMPORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=$VMDIR/known_hosts -o LogLevel=ERROR"
mkdir -p "$DIR"

ACCEL=tcg; CPU=cortex-a72
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) ACCEL=hvf; CPU=host ;;
  Linux-aarch64) [ -w /dev/kvm ] && { ACCEL=kvm; CPU=host; } ;;
esac

qemu_args() {
  printf '%s\n' \
    -name qosp \
    -machine "virt,accel=$ACCEL,gic-version=max" -cpu "$CPU" \
    -smp "${QOSP_CPUS:-4}" -m "${QOSP_MEM:-2G}" \
    -kernel "$DIR/Image" \
    -append "rootwait root=/dev/vda console=ttyAMA0 ${QOSP_APPEND:-}" \
    -drive "file=$DIR/rootfs.ext4,if=none,format=raw,id=hd0" \
    -device virtio-blk-pci,drive=hd0 \
    -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:$PORT-:22" \
    -device virtio-net-pci,netdev=n0 \
    -device virtio-gpu-pci \
    -device qemu-xhci,id=xhci -device usb-kbd,bus=xhci.0 -device usb-mouse,bus=xhci.0
}

have_image() {
  [ -f "$DIR/Image" ] && [ -f "$DIR/rootfs.ext4" ] || {
    echo "no image in $DIR: run '$0 pull' first" >&2; exit 1; }
}

# one arg per line through xargs -0, so the spaces inside -append survive
# (printf with no operands would emit one EMPTY argument, hence the guard)
run() {
  { qemu_args; [ $# -gt 0 ] && printf '%s\n' "$@"; } \
    | tr '\n' '\0' | xargs -0 qemu-system-aarch64
}

case "${1:-}" in
qemu-args)
  qemu_args
  ;;
pull)
  # -L: Buildroot leaves rootfs.ext4 as a symlink to rootfs.ext2, and a
  # copied symlink would dangle here
  rsync -aL --info=progress2 -e "ssh $SSHO" \
    "dev@127.0.0.1:$IMAGES/Image" "dev@127.0.0.1:$IMAGES/rootfs.ext4" "$DIR/"
  ls -la "$DIR"
  ;;
up)
  shift
  have_image
  : > "$DIR/serial.log"
  run -display none -serial "file:$DIR/serial.log" \
    -qmp "unix:$DIR/qmp.sock,server,nowait" \
    -daemonize -pidfile "$DIR/qemu.pid" "$@"
  echo "booting: console in $DIR/serial.log"
  ;;
gui)
  shift
  have_image
  case "$(uname -s)" in Darwin) D=cocoa ;; *) D=gtk ;; esac
  run -display "$D" -serial mon:stdio "$@"
  ;;
down)
  PID=$(cat "$DIR/qemu.pid" 2>/dev/null || true)
  [ -n "$PID" ] && { kill "$PID" 2>/dev/null || true; rm -f "$DIR/qemu.pid"; }
  ;;
*)
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
