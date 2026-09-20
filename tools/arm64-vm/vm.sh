#!/bin/sh
# vm.sh -- an Ubuntu arm64 guest for testing QOS Portable the way a Pi runs it:
# terminal only, a USB keyboard and mouse the guest sees as /dev/input/event*,
# and a QMP socket so a test can press the keys (inject.py).  On an Apple
# Silicon Mac it runs under the hypervisor, so it is as fast as the host.
#
#   vm.sh fetch      download the Ubuntu cloud image (~230 MB) and verify it
#   vm.sh create     make the disk, the ssh key and the cloud-init seed
#   vm.sh up | down  start (daemonized) / stop
#   vm.sh provision  apt-get the toolchain (needs network in the guest)
#   vm.sh sync       rsync both working trees to ~/fprisc and ~/qos (sources only)
#   vm.sh ssh [cmd]  a shell, or one command
#
# State lives in $QOS_VM_DIR (default ~/.cache/qos-arm64-vm).  Needs qemu
# (`brew install qemu`), rsync, ssh, hdiutil or genisoimage.  docs/INPUT.md.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
QOS=$(cd "$HERE/../.." && pwd)
DIR=${QOS_VM_DIR:-$HOME/.cache/qos-arm64-vm}
PORT=${QOS_VM_PORT:-2222}
IMG=ubuntu-24.04-minimal-cloudimg-arm64.img
URL=https://cloud-images.ubuntu.com/minimal/releases/noble/release
SSHO="-i $DIR/id_vm -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=$DIR/known_hosts -o LogLevel=ERROR"
mkdir -p "$DIR"

case "${1:-}" in
fetch)
  cd "$DIR"
  curl -fL -o "$IMG" "$URL/$IMG"
  curl -fsSL -o SHA256SUMS "$URL/SHA256SUMS"
  grep " \*$IMG\$" SHA256SUMS | shasum -a 256 -c -
  ;;
create)
  cd "$DIR"
  [ -f "$IMG" ] || { echo "no $IMG in $DIR: run '$0 fetch' first" >&2; exit 1; }
  [ -f id_vm ] || ssh-keygen -q -t ed25519 -N "" -C qos-arm64-vm -f id_vm
  # 72G because a Buildroot target (tools/buildroot) is ~12G of build tree
  # each, and having the QEMU test loop and the Pi image at once is the
  # point; qcow2 is sparse, so this costs what it uses
  qemu-img create -q -f qcow2 -F qcow2 -b "$IMG" disk.qcow2 "${QOS_VM_DISK:-72G}"
  FW=$(dirname "$(command -v qemu-system-aarch64)")/../share/qemu/edk2-aarch64-code.fd
  dd if=/dev/zero of=code.fd bs=1m count=64 2>/dev/null; dd if="$FW" of=code.fd conv=notrunc 2>/dev/null
  dd if=/dev/zero of=vars.fd bs=1m count=64 2>/dev/null
  rm -rf seed && mkdir seed
  printf 'instance-id: qos-arm64-1\nlocal-hostname: qos-arm64\n' > seed/meta-data
  # `input` is what lets an unprivileged process read /dev/input -- on a Pi too
  cat > seed/user-data <<SEED
#cloud-config
users:
  - name: dev
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    groups: [input, video, audio]
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
  case "$(uname -s)-$(uname -m)" in Darwin-arm64) ACCEL=hvf; CPU=host ;; Linux-aarch64) [ -w /dev/kvm ] && { ACCEL=kvm; CPU=host; } ;; esac
  qemu-system-aarch64 \
    -name qos-arm64 -machine virt,accel=$ACCEL,highmem=on -cpu $CPU -smp "${QOS_VM_CPUS:-4}" -m "${QOS_VM_MEM:-6G}" \
    -drive if=pflash,format=raw,readonly=on,file=code.fd \
    -drive if=pflash,format=raw,file=vars.fd \
    -drive if=virtio,format=qcow2,file=disk.qcow2 \
    -drive if=virtio,format=raw,readonly=on,file=seed.iso \
    -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$PORT-:22 -device virtio-net-pci,netdev=n0 \
    -device qemu-xhci,id=xhci -device usb-kbd,bus=xhci.0 -device usb-mouse,bus=xhci.0 \
    -qmp unix:qmp.sock,server,nowait \
    -display none -serial file:serial.log -daemonize -pidfile qemu.pid
  printf 'waiting for ssh'
  for _ in $(seq 90); do
    ssh $SSHO -o ConnectTimeout=2 dev@127.0.0.1 true 2>/dev/null && { echo " up"; exit 0; }
    printf .; sleep 2
  done
  echo " no ssh after 3 min: see $DIR/serial.log" >&2; exit 1
  ;;
down)
  PID=$(cat "$DIR/qemu.pid" 2>/dev/null || true)
  ssh $SSHO dev@127.0.0.1 sudo poweroff 2>/dev/null || true
  # a clean poweroff ends qemu (and removes its pidfile); otherwise end it
  [ -n "$PID" ] && { sleep 5; kill "$PID" 2>/dev/null || true; rm -f "$DIR/qemu.pid"; }
  ;;
provision)
  # what `make fpr`, `./qos.py build` and tools/gfx-gl-check.sh (a GL window under
  # Xvfb, software-rendered) need; no riscv toolchain or qemu: the
  # guest tests the arm64 HOST, the native kernel is tested where it is built
  ssh $SSHO dev@127.0.0.1 'sudo apt-get update -q && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    build-essential clang-18 lld make python3 rsync git \
    ghc libghc-megaparsec-dev libghc-network-dev libghc-utf8-string-dev \
    libegl-dev libgl-dev libglfw3-dev pkg-config libgl1-mesa-dri xvfb xdotool'
  ;;
sync)
  for r in fprisc qos; do
    rsync -a --delete -e "ssh $SSHO" \
      --exclude .git --exclude dist-newstyle --exclude '/build' --exclude '/.qos' --exclude '/dist' --exclude '/fpr' --exclude '/fprc' \
      --exclude '*.elf' --exclude '*.qa' --exclude '*.o' --exclude '*.hi' --exclude '/qos/qosp' --exclude '/qos/qosp-gl' --exclude '/qos/qosp-es' --exclude '/qos/qosp-a64' --exclude '/qos/build' \
      --exclude cabal.project.local --exclude __pycache__ --exclude .DS_Store \
      "$QOS/../$r/" dev@127.0.0.1:$r/
  done
  ;;
ssh)
  shift
  exec ssh $SSHO dev@127.0.0.1 "$@"
  ;;
*)
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
