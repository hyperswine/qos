#!/bin/sh
: "${FPRISC_ROOT:?Set FPRISC_ROOT to the fprisc checkout}"

# plugload-check.sh -- stage-2 verification (see plugload_check.c).
# Builds a stub plugin through the REAL link-qosplug.ld and the REAL
# tools/mkqa.py, then drives qosp's REAL bytes-based loader.

set -e
cd "$(dirname "$0")"
B=/tmp/plugcheck
rm -rf $B && mkdir -p $B

# ---- the stub plugin: one exported fn + an empty module table --------
cat > $B/plugstub.c <<'EOF'
typedef unsigned long uw;
uw plug_probe(uw x) { return x + 42; }
const uw fpr_modtab[4] = {0, 0, 0, 0};
EOF
gcc -O2 -ffreestanding -nostdlib -nostartfiles -static -fno-pic \
    -mcmodel=large -fno-asynchronous-unwind-tables \
    -T ../appside/link-qosplug.ld -Wl,--defsym=PLUG_BASE=0x408000000 \
    -Wl,--build-id=none -Wl,-z,noexecstack \
    $B/plugstub.c -o $B/plugstub.elf

echo "-- the two PT_LOADs (W^X split from link-qosplug.ld):"
readelf -l $B/plugstub.elf | grep -A1 "LOAD" | head -6
NLOAD=$(readelf -l $B/plugstub.elf | grep -c "^  LOAD") || true
[ "$NLOAD" = "2" ] || { echo "FAIL: expected 2 PT_LOADs, got $NLOAD"; exit 1; }

TAB=$(nm $B/plugstub.elf | awk '$3 == "fpr_modtab" { print $1 }')
PROBE=$(nm $B/plugstub.elf | awk '$3 == "plug_probe" { print $1 }')
echo "-- fpr_modtab @ 0x$TAB, plug_probe @ 0x$PROBE"

printf 'name = "plugstub"\nid = "plugstub"\nentry = "fpr_modtab"\nversion = "1"\nloadMode = "plugin"\n' \
  > $B/plugstub.toml
python3 ../../tools/mkqa.py $B/plugstub.toml $B/plugstub.elf -o $B/plugstub.qa

# ---- the harness: qosp's own objects, main renamed away --------------
gcc -O2 -Wall -Wextra -DFPR_POSIX -DFPR_NHARTS=8 \
    -I"$FPRISC_ROOT/runtime" -I../../hal/unix -I../appside \
    -Dmain=qosp_real_main -c ../portable/main.c -o $B/main.o
gcc -O2 -Wall -Wextra -DFPR_POSIX -DFPR_NHARTS=8 \
    -I"$FPRISC_ROOT/runtime" -I../../hal/unix -I../appside \
    plugload_check.c $B/main.o \
    ../portable/qa.c ../portable/haltab.c ../portable/store.c \
    ../../hal/unix/net_raw.c ../../hal/unix/blk_raw.c ../../hal/unix/hostlog.c \
    "$FPRISC_ROOT/runtime/buddy.c" ../../loader/qaimg.c \
    -o $B/plugload_check -lpthread

$B/plugload_check $B/plugstub.qa "$TAB" "$PROBE"
