#!/bin/sh
# Execute type-changing maps on Portable A64 and Native RV64.
set -eu
cd "$(dirname "$0")/.."
: "${FPRISC_ROOT:=$(cd ../fprisc && pwd)}"
export FPRISC_ROOT
W=$(mktemp -d /tmp/typedvector.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
P="$FPRISC_ROOT/tests/base/typedvector.fpr"
make -s qos-app PROG="$P" QA_OUT="$W/v.qa" >"$W/build.log" 2>&1 || { cat "$W/build.log"; exit 1; }
timeout 60 qos/qosp --yes "$W/v.qa" >"$W/portable.log" 2>&1
grep -a 'typed: 2 7 2.5 ok 2.25 3 True' "$W/portable.log"
make -s -C qos native SYSTEM="$P" KERNEL="$W/k.elf" >"$W/native-build.log" 2>&1 || { cat "$W/native-build.log"; exit 1; }
trap 'rm -rf "$W"; make -s -C qos native >/dev/null 2>&1 || true' EXIT INT TERM
rc=0
timeout 20 qemu-system-riscv64 -machine virt -smp 2 -m 256M -nographic -bios none -kernel "$W/k.elf" </dev/null >"$W/native.log" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || [ "$rc" -eq 124 ] || { cat "$W/native.log"; exit 1; }
grep -a 'typed: 2 7 2.5 ok 2.25 3 True' "$W/native.log"
