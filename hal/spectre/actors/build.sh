#!/bin/bash
set -eu
s=src
cc=riscv64-unknown-elf-gcc
f="${EXTRA:-} -march=rv32im_zicsr -mabi=ilp32 -mno-relax -msmall-data-limit=0 -ffixed-x27 -DFPR_NHARTS=1 -ffreestanding -fno-builtin -Os -ffunction-sections -fdata-sections -I$s/runtime -I$s/machine/virt"
$cc $f -Dhal_mtime=spectre_raw_ticks -Dhal_timer_arm=spectre_raw_arm -Dhal_putc=unused_uart -Dhal_poweroff=unused_poweroff -c $s/machine/virt/hal.c -o hal.o
$cc $f -nostdlib -Wl,--gc-sections -T $s/machine/tangnano20k/link.ld $s/machine/tangnano20k/crt0.S $s/machine/virt/{ctx.S,ctx_fab.c,memshim.c} $s/runtime/{runtime,actors,buddy,i32,sstr,vec}.c hal.o probe.c atomic.c -lgcc -o probe.elf
riscv64-unknown-elf-objcopy -O binary probe.elf probe.bin
