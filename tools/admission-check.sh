#!/bin/sh
# Real native process -> shared scheduler admission, one and two harts.
set -eu
cd "$(dirname "$0")/.."
: "${FPRISC_ROOT:=$(cd ../fprisc && pwd)}"
export FPRISC_ROOT
W=$(mktemp -d /tmp/qos-admission.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s -C qos native SYSTEM="$PWD/tests/admissionnative.fpr" KERNEL="$W/k.elf" >"$W/k.log" 2>&1 || { tail -25 "$W/k.log"; exit 1; }
printf 'name = "Memory admission probe"\nid = "CkMemory"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n' > "$W/app.toml"
tools/build-process-app.sh tests/memoryproc.fpr "$W/app.toml" "$W/CkMemory.qa" >"$W/a.log" 2>&1 || { tail -25 "$W/a.log"; exit 1; }
python3 tools/mkdisk.py "$W/d.img" 8 "$W/CkMemory.qa" >/dev/null
for harts in 1 2; do
  timeout 120 qemu-system-riscv64 -accel tcg,thread=multi -machine virt -smp "$harts" -m 256M -nographic -bios none \
    -kernel "$W/k.elf" -drive file="$W/d.img",if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0 \
    </dev/null >"$W/out-$harts.txt" 2>&1 || { tail -25 "$W/out-$harts.txt"; exit 1; }
  grep -a 'admissionnative: abi-refused=True process=\[memoryproc: invalid=True denied=True local=True pid=True overrun=True next=True escaped=42\] images=0 returned=True HOLDS' "$W/out-$harts.txt" || { tail -25 "$W/out-$harts.txt"; exit 1; }
done
