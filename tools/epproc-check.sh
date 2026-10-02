#!/bin/sh
# epproc-check.sh -- a loaded process reaches the namespace (tests/epproc.fpr):
# its grants were recorded under its pid before it ran, so a granted url
# opens, an ungranted one is refused by name, and its own storage stream
# round-trips.  QEMU virt, 2 harts; the launcher's permission prompts
# (its own four, then the process's three) are answered on stdin.
set -eu
cd "$(dirname "$0")/.."
: "${FPRISC_ROOT:=$(cd ../fprisc && pwd)}"
export FPRISC_ROOT
W=$(mktemp -d /tmp/epproc.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s -C qos native >"$W/k.log" 2>&1 || { tail -20 "$W/k.log"; exit 1; }
tools/build-process-app.sh tests/epproc.fpr tests/EpProc.toml "$W/EpProc.qa" >"$W/a.log" 2>&1 || { tail -20 "$W/a.log"; exit 1; }
python3 tools/mkdisk.py "$W/d.img" 8 "$W/EpProc.qa" >/dev/null
(printf 'yyyy'; sleep 6; printf '1'; sleep 3; printf 'yyy'; sleep 14) | timeout 40 qemu-system-riscv64 -accel tcg,thread=multi -machine virt -smp 2 -m 256M -nographic -bios none \
  -kernel qos/qos-native.elf -drive file="$W/d.img",if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0 \
  2>/dev/null | tr -d '\r' > "$W/out.txt" || true
grep -a "epproc: hello through the namespace" "$W/out.txt" >/dev/null || { echo "epproc: the process's display write did not reach the console"; tail -c 1500 "$W/out.txt"; exit 1; }
grep -a "process exited: epproc: display=ok clock=ok ungranted=not granted: /pins/1 (read) kv=ok" "$W/out.txt"
