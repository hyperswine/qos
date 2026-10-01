#!/bin/sh
# nativeimage-check.sh -- native process images are memory like any other
# (docs/2026-10-01-PROCESS-IMAGES.md), on QEMU virt: two processes run at
# once, an image stays while any actor of its process runs and then goes,
# and the memory comes back.  Builds a TEST KERNEL (tests/nativeimage.fpr in
# place of system.fpr) and two relocatable process images.
set -eu
cd "$(dirname "$0")/.."
: "${FPRISC_ROOT:=$(cd ../fprisc && pwd)}"
export FPRISC_ROOT
W=$(mktemp -d /tmp/nativeimage.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s -C qos native SYSTEM="$PWD/tests/nativeimage.fpr" KERNEL="$W/k.elf" >"$W/k.log" 2>&1 || { tail -20 "$W/k.log"; exit 1; }
for a in CkSlow:slowproc CkLinger:lingerproc; do
  id=${a%%:*}; src=${a##*:}
  printf 'name = "%s"\nid = "%s"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n' "$id" "$id" >"$W/$id.toml"
  tools/build-process-app.sh "tests/$src.fpr" "$W/$id.toml" "$W/$id.qa" >"$W/$id.log" 2>&1 || { tail -20 "$W/$id.log"; exit 1; }
done
python3 tools/mkdisk.py "$W/d.img" 8 "$W/CkSlow.qa" "$W/CkLinger.qa" >/dev/null
# the kernel build above left build/system.s as the test kernel's
trap 'rm -rf "$W"; make -s -C qos native >/dev/null 2>&1 || true' EXIT INT TERM
timeout 180 qemu-system-riscv64 -accel tcg,thread=multi -machine virt -smp 2 -m 256M -nographic -bios none \
  -kernel "$W/k.elf" -drive file="$W/d.img",if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0 \
  </dev/null 2>/dev/null | tr -d '\r' | grep -a "nativeimage: concurrent=both-intact linger=held-then-freed images=0 memory=returned HOLDS"
