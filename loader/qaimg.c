/* qaimg.c -- placing a QAR2 flat image (docs/2026-07-19-QA-FORMAT.md).
 *
 * The load path used to live here whole: a hand-rolled `key <decimal>`
 * scanner over the LOAD section's text and five consistency refusals, then
 * the copy.  The text is read in FP-RISC now (programs/mods/qaimg.fpr), by
 * each of the three loaders -- the portable host, an app attaching a plugin,
 * the native kernel -- because each has FP-RISC on its side of the call.
 *
 * What stays is what guards and performs a copy, freestanding by
 * construction (byte loops, no libc): the image must lie inside the window
 * it was given; then copy it there and zero its bss tail.  Protection
 * (mprotect r-x / PMP) is the host's, with the boundaries reported here.
 */
#include "fpr.h"

static fpr_elf_load_t qfail(const char *why) {
  fpr_elf_load_t r = {0, 0, 0, why, 0, (void *)~(uw)0};
  return r;
}

fpr_elf_load_t fpr_qaimg_place(const fpr_qaimg_t *q, const unsigned char *img, uw img_len,
                               void *window, uw window_size) {
  /* the copy's own preconditions -- not policy: without them the loops below
   * write outside what the caller owns */
  if (img_len > q->memsz) return qfail("IMAGE larger than the memory it claims");
  uw wlo = (uw)window, whi = wlo + window_size;
  if (q->base < wlo || q->base + q->memsz > whi || q->base + q->memsz < q->base)
    return qfail("image outside the load window");

  unsigned char *dst = (unsigned char *)q->base;
  for (uw i = 0; i < img_len; i++) dst[i] = img[i];
  for (uw i = img_len; i < q->memsz; i++) dst[i] = 0;

  fpr_elf_load_t r;
  r.ok = 1;
  r.err = 0;
  r.entry = (void *)(q->base + q->entry);
  r.image_end = (void *)(q->base + q->memsz);
  r.exec_end = (void *)(q->base + q->execsz);
  r.rw_start = q->rwoff < q->memsz ? (void *)(q->base + q->rwoff) : (void *)~(uw)0;
  return r;
}

/* move a RELOCATABLE image (linked at 0) to where it was placed: each RELOC
 * entry is the little-endian u32 offset of an address word in the image's
 * file bytes, which gets the placement address added
 * (docs/2026-10-01-PROCESS-IMAGES.md).  The build verified the list
 * (tools/mkqa.py --check-moved); this checks only that every word lies
 * inside the bytes that were copied, since a write outside them is not ours
 * to make.  Returns 0, or why not. */
const char *fpr_qaimg_relocate(unsigned char *dst, uw img_len,
                               const unsigned char *rel, uw rel_len) {
  if (rel_len % 4) return "RELOC is not a whole number of entries";
  uw delta = (uw)dst;
  for (uw i = 0; i < rel_len; i += 4) {
    uw off = (uw)rel[i] | (uw)rel[i + 1] << 8 | (uw)rel[i + 2] << 16 | (uw)rel[i + 3] << 24;
    if (off + 8 > img_len || off + 8 < off) return "a RELOC entry outside the image";
    uw w = 0;
    for (int k = 7; k >= 0; k--) w = w << 8 | dst[off + (uw)k];
    w += delta;
    for (int k = 0; k < 8; k++) { dst[off + (uw)k] = (unsigned char)w; w >>= 8; }
  }
  return 0;
}
