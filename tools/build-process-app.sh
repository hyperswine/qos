#!/usr/bin/env bash
: "${FPRISC_ROOT:?Set FPRISC_ROOT to the fprisc checkout}"

# build-process-app.sh -- build a dynamically-loadable QOS process app
# and wrap it in a QAR2 .qa with loadMode = "process" set.
# (docs/2026-07-19-QA-FORMAT.md; docs/PROCESS-LOADING.md has the original design.)
#
# Usage: tools/build-process-app.sh <app.fpr> <manifest.toml> <out.qa> [rv32|rv64]
#
# The image is RELOCATABLE (docs/2026-10-01-PROCESS-IMAGES.md): linked at 0
# with --emit-relocs, and mkqa.py writes the RELOC section the kernel applies
# wherever Memory.qa's buddy put the block.  Nothing is linked against the
# kernel, so any kernel build loads it.  A second link 256 MiB higher checks
# the relocation list: the two images must differ at exactly those words.
# The ELFs built here are toolchain intermediates.

set -euo pipefail
APP_FPR="$1"; MANIFEST="$2"; OUT_QA="$3"; TARGET="${4:-rv64}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export FPR_HOME="$ROOT"
export FPR_PATH="$FPRISC_ROOT"
export FPR_FOREIGN="$ROOT/core/foreign.fpr"
RUNTIME="$FPRISC_ROOT/runtime"
MACHINE="$FPRISC_ROOT/machine"
QOS=qos   # relative to the repository root (it was ../qos from fp-risc/tools/, before the programs moved up)
if [ "$TARGET" = rv32 ]; then
  ARCHFLAGS="-march=rv32imac_zicsr -mabi=ilp32"; WORDSZ=4
else
  ARCHFLAGS="-march=rv64imafdc_zicsr -mabi=lp64 -mcmodel=medany"; WORDSZ=8
fi

[ "$TARGET" = rv64 ] || { echo "native process images are rv64 (relocation is implemented for R_RISCV_64)" >&2; exit 1; }
echo "target=$TARGET  relocatable (linked at 0)"

BASE=$(basename "$APP_FPR" .fpr)
mkdir -p build
LC_ALL=C.UTF-8 "$FPRISC_ROOT/fpr" --target="$TARGET" --prelude="$FPRISC_ROOT/core/prelude.fpr" "$APP_FPR" "build/${BASE}.s"

# the virt HAL's PLIC and CLINT drivers are FP-RISC raw library units; the
# compiler tree's make fragment owns their rules and export lists
make -s -f "$MACHINE/virt/virt.mk" FPRC="$FPRISC_ROOT/fpr" BUILD=build VIRT_MACHINE="$MACHINE" build/virt-clint.s
make -s -f hal/virt/qos-virt.mk FPRC="$FPRISC_ROOT/fpr" BUILD=build QOS_HAL=hal build/qos-plic.s build/qos-virtio.s build/qos-blockpolicy.s build/qos-netpolicy.s
VIRT_FPR="build/virt-clint.s $MACHINE/virt/rawunit.c build/qos-plic.s build/qos-virtio.s build/qos-blockpolicy.s build/qos-netpolicy.s hal/virt/plic.c hal/virt/net.c hal/net_actor_bridge.c hal/virt/blk.c hal/virt/pins.c hal/virt/devices.c"

RT="$VIRT_FPR $QOS/native/proc_entry.c $MACHINE/virt/ctx.S $MACHINE/virt/ctx_fab.c $RUNTIME/runtime.c $MACHINE/virt/hal.c $MACHINE/virt/memshim.c $RUNTIME/actors.c $RUNTIME/buddy.c $RUNTIME/mod.c $RUNTIME/bits.c $RUNTIME/vec.c $RUNTIME/sstr.c"
link() { # link <base> <out.elf>
  riscv64-unknown-elf-gcc $ARCHFLAGS -DFPR_NHARTS=1 -ffreestanding -nostdlib -nostartfiles -O2 \
    -Wl,--defsym=PROC_IMAGE_BASE=$1 -Wl,--emit-relocs -Wl,--no-relax -Wl,--no-warn-rwx-segments \
    -Wl,--defsym=_heap_start=_proc_image_end \
    -Wl,--defsym=_heap_end=_proc_image_end -Wl,--defsym=_proc_arena_end=_proc_image_end \
    -T $MACHINE/virt/link-app.ld -I$RUNTIME -I$MACHINE/virt $RT "build/${BASE}.s" $(cat "build/${BASE}.s.units") -o "$2"
}
link 0 "build/${BASE}.elf"
link 0x10000000 "build/${BASE}.moved.elf"

NATIVE_ABI=$(python3 -c 'import re,sys; print(re.search(r"^#define FPR_NATIVE_ABI (\d+)u", open(sys.argv[1]).read(), re.M)[1])' "$RUNTIME/fpr.h")
python3 tools/mkqa.py "$MANIFEST" "build/${BASE}.elf" -o "$OUT_QA" --relocatable \
  --check-moved "build/${BASE}.moved.elf" --delta 0x10000000 --native-abi "$NATIVE_ABI"
echo "wrote $OUT_QA (loadMode=process, relocatable; seed it with tools/mkdisk.py for a disk boot)"
