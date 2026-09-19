/* link-qosapp-a64.ld -- fixed-slot linker script for QOS-aarch64 app images.
 * Same layout and contract as link-qosapp.ld; only OUTPUT_FORMAT/ARCH differ.
 */
OUTPUT_FORMAT("elf64-littleaarch64")
OUTPUT_ARCH(aarch64)
ENTRY(qos_app_entry)

MEMORY { SLOT (rwx) : ORIGIN = QOS_SLOT_BASE, LENGTH = 1024M }

/* Two PT_LOADs so the host can enforce W^X: code+rodata r-x, data+bss
 * rw.  The 64 KiB alignment between them means no host page round-up
 * (4 KiB Linux, 16 KiB Apple Silicon) can pull a writable byte into
 * the executable prefix -- the boundary main.c refuses to blur. */
PHDRS {
  text PT_LOAD FLAGS(5); /* r-x */
  data PT_LOAD FLAGS(6); /* rw- */
}

SECTIONS {
  .text : { *(.text .text.*) } > SLOT :text
  .rodata : { *(.rodata .rodata.*) } > SLOT :text
  .data : ALIGN(0x10000) { *(.data .data.* .got .got.plt) } > SLOT :data
  .bss (NOLOAD) : {
    . = ALIGN(8); _bss_start = .;
    *(.bss .bss.*) *(COMMON)
    . = ALIGN(8); _bss_end = .;
  } > SLOT :data
  . = ALIGN(16); _proc_image_end = .; /* where the heap hand-off starts */

  /DISCARD/ : { *(.note.* .comment .eh_frame .eh_frame_hdr .rela.*) }
}
