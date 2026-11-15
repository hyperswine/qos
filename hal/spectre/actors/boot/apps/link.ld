ENTRY(_start)
SECTIONS { . = 0; .text : { KEEP(*(.text.entry)) *(.text*) } .rodata : { *(.rodata*) } /DISCARD/ : { *(.comment) *(.riscv.attributes) } }
