#!/bin/sh
# SUPERVISION S8: `error` inside a loaded process ends that process's actor
# (fail-stop through the plane), and the machine continues.  Until 2026-10-10
# the image's own panic path halted the machine.
set -eu
cd "$(dirname "$0")/.."
: "${FPRISC_ROOT:=$(cd ../fprisc && pwd)}"
export FPRISC_ROOT
W=$(mktemp -d /tmp/qos-errorproc.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s -C qos native SYSTEM="$PWD/tests/errornative.fpr" BUILD="$W/kernel" KERNEL="$W/k.elf" >"$W/k.log" 2>&1 || { tail -25 "$W/k.log"; exit 1; }
printf 'name = "Error in a process"\nid = "CkError"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n' > "$W/app.toml"
tools/build-process-app.sh tests/errorproc.fpr "$W/app.toml" "$W/CkError.qa" >"$W/a.log" 2>&1 || { tail -25 "$W/a.log"; exit 1; }
python3 tools/mkdisk.py "$W/d.img" 8 "$W/CkError.qa" >/dev/null
for harts in 1 2; do
  timeout 60 qemu-system-riscv64 -accel tcg,thread=multi -machine virt -smp "$harts" -m 256M -nographic -bios none \
    -kernel "$W/k.elf" -drive file="$W/d.img",if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0 \
    </dev/null >"$W/out-$harts.txt" 2>&1 || true
  grep -a 'errornative: process=\[failed: dead actor\] images=0 MACHINE-CONTINUED' "$W/out-$harts.txt" >/dev/null \
    || { echo "== $harts hart(s): the machine did not continue =="; grep -a -E 'errorproc|errornative|PANIC|actor failed' "$W/out-$harts.txt" | head -8; exit 1; }
  grep -a -q 'actor failed: errorproc: deliberate' "$W/out-$harts.txt" || { echo "the reason was not logged"; exit 1; }
  echo "error in a loaded process ends that actor, the machine continues: $harts hart(s) HOLDS"
done
