#!/usr/bin/env bash
: "${FPRISC_ROOT:?Set FPRISC_ROOT to the fprisc checkout}"

# build-process-app.sh -- build a dynamically-loadable QOS process app
# and wrap it in a QAR2 .qa with loadMode = "process" set.
# (docs/QA-FORMAT.md; docs/PROCESS-LOADING.md has the original design.)
#
# Usage: tools/build-process-app.sh <app.fpr> <manifest.toml> <out.qa> [rv32|rv64]
#
# The kernel is qos/qos-native.elf (`make -C qos native` first) -- its _proc_arena_start is the slot address
# this app gets linked against.  The ELF built here is a toolchain
# intermediate: mkqa.py flattens it into the QAR2 IMAGE at the end.

set -euo pipefail
APP_FPR="$1"; MANIFEST="$2"; OUT_QA="$3"; TARGET="${4:-rv64}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export FPR_HOME="$ROOT"
export FPR_PATH="$FPRISC_ROOT"
RUNTIME="$FPRISC_ROOT/runtime"
MACHINE="$FPRISC_ROOT/machine"
QOS=qos   # relative to the repository root (it was ../qos from fp-risc/tools/, before the programs moved up)
KERNEL=$QOS/qos-native.elf

[ -f "$KERNEL" ] || { echo "$KERNEL not found -- run 'make -C qos native' first" >&2; exit 1; }

if [ "$TARGET" = rv32 ]; then
  ARCHFLAGS="-march=rv32imac_zicsr -mabi=ilp32"; WORDSZ=4
else
  ARCHFLAGS="-march=rv64imafdc_zicsr -mabi=lp64 -mcmodel=medany"; WORDSZ=8
fi

ARENA_HEX=$(riscv64-unknown-elf-nm "$KERNEL" | awk '/ _proc_arena_start$/{print $1}')
[ -n "$ARENA_HEX" ] || { echo "could not find _proc_arena_start in $KERNEL" >&2; exit 1; }
# the true first-allocation address is arena_base + sizeof(uw): buddy_alloc
# returns a pointer past its own bookkeeping header (docs/PROCESS-LOADING.md)
SLOT_BASE=$(printf '0x%x' $((0x$ARENA_HEX + WORDSZ)))
echo "target=$TARGET  _proc_arena_start=0x$ARENA_HEX  PROC_SLOT_BASE=$SLOT_BASE"

BASE=$(basename "$APP_FPR" .fpr)
mkdir -p build
LC_ALL=C.UTF-8 "$FPRISC_ROOT/fpr" --target="$TARGET" --prelude="$FPRISC_ROOT/core/prelude.fpr" "$APP_FPR" "build/${BASE}.s"

# the virt HAL's PLIC and CLINT drivers are FP-RISC raw library units; the
# compiler tree's make fragment owns their rules and export lists
make -s -f "$MACHINE/virt/virt.mk" FPRC="$FPRISC_ROOT/fpr" BUILD=build VIRT_MACHINE="$MACHINE" build/virt-clint.s
make -s -f hal/virt/qos-virt.mk FPRC="$FPRISC_ROOT/fpr" BUILD=build QOS_HAL=hal build/qos-plic.s
VIRT_FPR="build/virt-clint.s $MACHINE/virt/rawunit.c build/qos-plic.s hal/virt/plic.c hal/virt/net.c hal/virt/blk.c hal/virt/pins.c hal/virt/devices.c"

RT="$VIRT_FPR $QOS/native/proc_entry.c $MACHINE/virt/ctx.S $MACHINE/virt/ctx_fab.c $RUNTIME/runtime.c $MACHINE/virt/hal.c $MACHINE/virt/memshim.c $RUNTIME/actors.c $RUNTIME/buddy.c $RUNTIME/mod.c $RUNTIME/bits.c $RUNTIME/vec.c $RUNTIME/sstr.c"
riscv64-unknown-elf-gcc $ARCHFLAGS -DFPR_NHARTS=1 -ffreestanding -nostdlib -nostartfiles -O2 \
  -Wl,--defsym=PROC_SLOT_BASE=$SLOT_BASE \
  -Wl,--defsym=_heap_start=_proc_image_end \
  -Wl,--defsym=_heap_end=_proc_image_end -Wl,--defsym=_proc_arena_end=0x84000000 \
  -T $MACHINE/virt/link-app.ld -I$RUNTIME -I$MACHINE/virt $RT "build/${BASE}.s" $(cat "build/${BASE}.s.units") -o "build/${BASE}.elf"

python3 tools/mkqa.py "$MANIFEST" "build/${BASE}.elf" -o "$OUT_QA"
echo "wrote $OUT_QA (loadMode=process; seed it with tools/mkdisk.py for a disk boot)"
