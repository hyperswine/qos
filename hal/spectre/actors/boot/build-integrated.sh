#!/usr/bin/env bash
# Build the integrated Spectre kernel, SD installer, FPGA image and app fixtures.
set -euo pipefail
boot=$(cd "$(dirname "$0")" && pwd)
qos=$(cd "$boot/../../../.." && pwd)
fprisc=$(cd "${FPRISC:-$qos/../fprisc}" && pwd)
board=$(cd "${SIMPLE_RISC:-$qos/../simple-risc}" && pwd)
out=${1:?usage: build-integrated.sh NEW-OUTPUT-DIRECTORY}
mkdir "$out"
cd "$out"
out=$PWD
export LC_ALL=C
unset EXTRA
mkdir -p src boot/apps board
pin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$qos/fprisc.lock.json")
git -C "$fprisc" archive "$pin" runtime machine/virt machine/tangnano20k | tar -x -C src
board_pin=8f83a6d165dae080110312cdbde40d32799a461a
git -C "$board" archive "$board_pin" boards/tangnano20k/c boards/tangnano20k/bootrom | tar -x -C board
preset=output/tangnano20k/btbdef-54
mkdir -p "board/$preset/impl/pnr"
cp "$board/$preset/impl/pnr/sdram_test.fs" "board/$preset/impl/pnr/"
cp "$board/$preset/bootrom-sdram.hex" "board/$preset/"
export SIMPLE_RISC="$out/board"
cp "$boot/../atomic.c" .
cp "$boot"/{app.fpr,hal.c,build.sh,build-media.sh,rom.c,install.c,media.S,mkmedia.py,patchrom.py,check-writable.py} boot/
cp "$boot"/../vfs/{pack.py,unpack.S} boot/
cp "$boot"/apps/{*.fpr,entry.S,link.ld,build-app.py,check-two.py} boot/apps/
# FP-RISC orders module-table entries by resolved source path. Give both
# source roots stable relative names, independent of checkout locations.
mkdir fprisc qos
cp -R "$fprisc/core" "$fprisc/std" fprisc/
cp -R "$qos/core" "$qos/std" "$qos/programs" "$qos/.fpr" qos/
export FPR_HOME="$out/qos" FPR_PATH="$out/fprisc" FPR_FOREIGN="$out/qos/core/foreign.fpr"
(cd boot && "$fprisc/fpr" compile --target=rv32 --prelude="$FPR_PATH/core/prelude.fpr" app.fpr app.s)
bash boot/build.sh
(cd boot && bash build-media.sh)
(cd boot/apps
 for name in spin pendulum hello; do python3 build-app.py "$name.fpr" "$fprisc/fpr"; done
 for name in ping pong; do python3 build-app.py "$name.fpr" "$fprisc/fpr" --mailbox; done)
shasum -a 256 boot/{fs.bin,media.bin,install.bin,patched-pre.fs} boot/apps/*.sxa > SHA256SUMS
{ echo "runtime $pin"; echo "board $board_pin"; git -C "$qos" rev-parse HEAD; git -C "$fprisc" rev-parse HEAD; shasum -a 256 "$fprisc/fpr" "$fprisc/core/prelude.fpr"; riscv64-unknown-elf-gcc --version; } > build-inputs.txt
cat SHA256SUMS
