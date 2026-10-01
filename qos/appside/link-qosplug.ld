/* link-qosplug.ld -- a plugin .qa image (docs/2026-10-01-IMPORT-TABLE.md):
 * its generated code, its own copy of what it was compiled with (the
 * prelude, its modules), and its module table -- linked at PLUG_BASE = 0
 * with --emit-relocs.  The app places it in a block of its own heap, moves
 * its address words (RELOC) and completes its imports of the runtime by
 * name from its export table (IMPORT; tools/mkimports.py made the stubs).
 *
 * ENTRY is the MODULE TABLE, not code: mkqa.py records e_entry in the
 * LOAD section, the host hands it back from tag 4, and fpr_mod_attach
 * registers it -- the table's address IS the plugin's identity.
 *
 * Two PT_LOADs, explicitly (the link-qosapp lesson): text+rodata r-x,
 * data+bss rw, ALIGN(0x10000) between them so the W^X boundary is real
 * on 4 K and 16 K pages alike (the app places the image on a 64 KiB
 * boundary, so the alignment holds wherever it lands). */
ENTRY(fpr_modtab)
PHDRS {
  text PT_LOAD;
  data PT_LOAD;
}
SECTIONS {
  . = PLUG_BASE;
  .text : { *(.text .text.*) } :text
  .rodata : ALIGN(16) { *(.rodata .rodata.*) *(.srodata*) } :text
  . = ALIGN(0x10000);
  .data : { *(.data .data.*) *(.sdata*) } :data
  .bss : { *(.bss .bss.*) *(.sbss*) *(COMMON) } :data
  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
