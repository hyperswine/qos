#!/bin/bash
# Run inside boot/ after fs.bin was linked via build.sh from the scratch root.
set -eu
: "${SIMPLE_RISC:?set Simple-Risc checkout}"
b="$SIMPLE_RISC/boards/tangnano20k"
cc=riscv64-unknown-elf-gcc
obj=riscv64-unknown-elf-objcopy
base=(-march=rv32im_zicsr_zifencei -mabi=ilp32 -mno-relax -msmall-data-limit=0 -Os -ffreestanding -nostdlib)
"$cc" "${base[@]}" -DROM_SDRAM -T "$b/bootrom/link.ld" "$b/bootrom/crt0.S" rom.c -o rom.elf
"$obj" -O binary rom.elf rom.bin
python3 pack.py
"$cc" "${base[@]}" -Ttext=0x80000000 unpack.S -o packed.elf
"$obj" -j .text -O binary packed.elf packed.bin
python3 mkmedia.py
python3 patchrom.py
cd ..
"$cc" "${base[@]}" -T src/machine/tangnano20k/link.ld src/machine/tangnano20k/crt0.S -I"$b/c" "$b/c/sd.c" boot/install.c boot/media.S -o boot/install.elf
"$obj" -O binary boot/install.elf boot/install.bin
