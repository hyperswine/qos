#!/bin/sh
# vm.sh -- a FreeBSD arm64 guest, to prove QOS Portable is not a Linux
# program.  The SERVER shape only: no graphics, no input devices, nothing
# from ports.  A stock FreeBSD release image, a key, and a socket.
#
#   vm.sh fetch      download the FreeBSD cloud image (~558 MB) and verify it
#   vm.sh create     make the disk and the cloud-init seed
#   vm.sh up | down  start (daemonized) / stop
#   vm.sh ssh [cmd]  a shell, or one command
#   vm.sh put F [D]  copy a file in (scp; FreeBSD base has no rsync)
#   vm.sh sysroot D  copy the guest's headers and libraries OUT, so the
#                    Linux box can cross-compile against this exact release
#
# Deliberately lean: nothing is installed in the guest.  qosp is built
# elsewhere and copied in, which is the point -- it links libc and libm
# and nothing else, so a FreeBSD release image needs no help to run it.
#
# Sibling of tools/arm64-vm/vm.sh (the Ubuntu guest); same shape, its own
# state in $QOS_BSD_DIR (default ~/.cache/qos-freebsd-vm) and its own port.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DIR=${QOS_BSD_DIR:-$HOME/.cache/qos-freebsd-vm}
PORT=${QOS_BSD_PORT:-2224}
# a second forward, so a server running in the guest answers on the host
APORT=${QOS_BSD_APP_PORT:-8080}
REL=${QOS_BSD_REL:-14.5-RELEASE}
IMG=FreeBSD-$REL-arm64-aarch64-BASIC-CLOUDINIT-ufs.qcow2
URL=https://download.freebsd.org/releases/VM-IMAGES/$REL/aarch64/Latest
# `dev`, not root: FreeBSD's sshd refuses root by default and cloud-init
# does not change that.  Everything here needs no privilege -- the sysroot
# is world-readable and a test server binds a high port.
SSHO="-i $DIR/id_vm -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=$DIR/known_hosts -o LogLevel=ERROR"
USER_AT=dev@127.0.0.1
mkdir -p "$DIR"

case "${1:-}" in
fetch)
  cd "$DIR"
  [ -f "$IMG" ] || {
    curl -fL -o "$IMG.xz" "$URL/$IMG.xz"
    curl -fsSL -o CHECKSUM.SHA256 "$URL/CHECKSUM.SHA256" || true
    if [ -f CHECKSUM.SHA256 ]; then
      WANT=$(grep "($IMG.xz)" CHECKSUM.SHA256 | sed 's/.*= //')
      GOT=$(shasum -a 256 "$IMG.xz" | awk '{print $1}')
      [ "$WANT" = "$GOT" ] || { echo "checksum MISMATCH for $IMG.xz" >&2; exit 1; }
      echo "sha256 ok: $GOT"
    else
      echo "warning: no CHECKSUM.SHA256 published; image unverified" >&2
    fi
    xz -d "$IMG.xz"
  }
  ls -la "$IMG"
  ;;
create)
  cd "$DIR"
  [ -f "$IMG" ] || { echo "no $IMG in $DIR: run '$0 fetch' first" >&2; exit 1; }
  [ -f id_vm ] || ssh-keygen -q -t ed25519 -N "" -C qos-freebsd-vm -f id_vm
  qemu-img create -q -f qcow2 -F qcow2 -b "$IMG" disk.qcow2 "${QOS_BSD_DISK:-32G}"
  FW=$(dirname "$(command -v qemu-system-aarch64)")/../share/qemu/edk2-aarch64-code.fd
  dd if=/dev/zero of=code.fd bs=1m count=64 2>/dev/null; dd if="$FW" of=code.fd conv=notrunc 2>/dev/null
  dd if=/dev/zero of=vars.fd bs=1m count=64 2>/dev/null
  rm -rf seed && mkdir seed
  printf 'instance-id: qos-freebsd-1\nlocal-hostname: qos-freebsd\n' > seed/meta-data
  # one unprivileged user with a key.  FreeBSD base has no sudo and its
  # sshd refuses root, and nothing here wants either: the build happens
  # elsewhere, and a test server binds a high port.
  cat > seed/user-data <<SEED
#cloud-config
users:
  - name: dev
    shell: /bin/sh
    ssh_authorized_keys:
      - $(cat id_vm.pub)
ssh_pwauth: false
growpart: {mode: auto, devices: ['/']}
SEED
  rm -f seed.iso
  if command -v hdiutil >/dev/null; then
    hdiutil makehybrid -quiet -o seed.iso -iso -joliet -default-volume-name cidata seed
  else
    genisoimage -quiet -output seed.iso -volid cidata -joliet -rock seed/user-data seed/meta-data
  fi
  echo "created in $DIR"
  ;;
up)
  cd "$DIR"
  ACCEL=tcg; CPU=max
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) ACCEL=hvf; CPU=host ;;
    Linux-aarch64) [ -w /dev/kvm ] && { ACCEL=kvm; CPU=host; } ;;
  esac
  qemu-system-aarch64 \
    -name qos-freebsd -machine virt,accel=$ACCEL,highmem=on -cpu $CPU \
    -smp "${QOS_BSD_CPUS:-4}" -m "${QOS_BSD_MEM:-4G}" \
    -drive if=pflash,format=raw,readonly=on,file=code.fd \
    -drive if=pflash,format=raw,file=vars.fd \
    -drive if=virtio,format=qcow2,file=disk.qcow2 \
    -drive if=virtio,format=raw,readonly=on,file=seed.iso \
    -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$PORT-:22,hostfwd=tcp:127.0.0.1:$APORT-:$APORT \
    -device virtio-net-pci,netdev=n0 \
    -qmp unix:qmp.sock,server,nowait \
    -display none -serial file:serial.log -daemonize -pidfile qemu.pid
  printf 'waiting for ssh'
  for _ in $(seq 120); do
    ssh $SSHO -o ConnectTimeout=2 $USER_AT true 2>/dev/null && { echo " up"; exit 0; }
    printf .; sleep 2
  done
  echo " no ssh after 4 min: see $DIR/serial.log" >&2; exit 1
  ;;
down)
  PID=$(cat "$DIR/qemu.pid" 2>/dev/null || true)
  # ACPI shutdown through QEMU's own monitor rather than a login: no root
  # ssh, no password, and FreeBSD runs its real shutdown so the UFS root
  # is clean on the next boot instead of being fsck'd
  if [ -S "$DIR/qmp.sock" ]; then
    python3 - "$DIR/qmp.sock" <<'PY' 2>/dev/null || true
import json, socket, sys
s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
f = s.makefile("rw", encoding="utf-8", newline="\n")
f.readline()  # the greeting
for c in ({"execute": "qmp_capabilities"}, {"execute": "system_powerdown"}):
    f.write(json.dumps(c) + "\n")
    f.flush()
    f.readline()
PY
  fi
  if [ -n "$PID" ]; then
    for _ in $(seq 40); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
    kill "$PID" 2>/dev/null || true
    rm -f "$DIR/qemu.pid"
  fi
  ;;
ssh)
  shift
  exec ssh $SSHO $USER_AT "$@"
  ;;
put)
  [ -n "${2:-}" ] || { echo "usage: $0 put FILE [DEST]" >&2; exit 2; }
  # scp spells the port -P; -p would mean "preserve times" and eat the number
  exec scp -i "$DIR/id_vm" -P "$PORT" -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile="$DIR/known_hosts" -o LogLevel=ERROR \
    "$2" $USER_AT:"${3:-./}"
  ;;
sysroot)
  # what a cross compiler needs and nothing else: the headers, the static
  # link bits, and the shared libraries it resolves against
  OUT=${2:?usage: $0 sysroot DIR}
  mkdir -p "$OUT"
  ssh $SSHO $USER_AT \
    'tar cf - /usr/include /usr/lib/*.a /usr/lib/*.so* /usr/lib/crt*.o /lib/*.so* 2>/dev/null' \
    | tar xf - -C "$OUT"
  echo "sysroot in $OUT ($(du -sh "$OUT" | awk '{print $1}'))"
  ;;
*)
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
