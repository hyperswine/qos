#!/bin/sh
# The Base mailbox contract (tests/mailbox.fpr) as a loaded native process:
# a Static ring refuses and says so, a Dynamic ring grows in order, a dead
# actor answers -- through the plane's actors table, one and two harts.
set -eu
cd "$(dirname "$0")/.."
: "${FPRISC_ROOT:=$(cd ../fprisc && pwd)}"
export FPRISC_ROOT
W=$(mktemp -d /tmp/qos-mailboxproc.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s -C qos native SYSTEM="$PWD/tests/mailboxnative.fpr" BUILD="$W/kernel" KERNEL="$W/k.elf" >"$W/k.log" 2>&1 || { tail -25 "$W/k.log"; exit 1; }
printf 'name = "Mailbox contract probe"\nid = "CkMailbox"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n' > "$W/app.toml"
tools/build-process-app.sh tests/mailboxproc.fpr "$W/app.toml" "$W/CkMailbox.qa" >"$W/a.log" 2>&1 || { tail -25 "$W/a.log"; exit 1; }
python3 tools/mkdisk.py "$W/d.img" 8 "$W/CkMailbox.qa" >/dev/null
for harts in 1 2; do
  timeout 120 qemu-system-riscv64 -accel tcg,thread=multi -machine virt -smp "$harts" -m 256M -nographic -bios none \
    -kernel "$W/k.elf" -drive file="$W/d.img",if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0 \
    </dev/null >"$W/out-$harts.txt" 2>&1 || { tail -25 "$W/out-$harts.txt"; exit 1; }
  grep -a 'mailboxnative: process=\[mailbox: static 8 queued 8 of 20 (12 refused), drained 8 in order; dynamic 8 queued 20 of 20, drained 20 in order; arc 3000 shared values held, drained 3000 in order; a dead actor answers dead actor\] images=0 HOLDS' "$W/out-$harts.txt" >/dev/null || { tail -25 "$W/out-$harts.txt"; exit 1; }
  echo "mailbox contract as a process: $harts hart(s) HOLDS"
done
