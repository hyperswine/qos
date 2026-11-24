/* imgcache.h -- the launch path's one-entry "already verified" record.
 *
 * Sys.checkImage hashes a native image's IMAGE and RELOC+IMPORT with SHA-256
 * before the launcher reserves a pid; Sys.placeImageAt repeats the gate. When
 * placement follows a check of the very same bytes, the second SHA-256 (about
 * 80 instructions a byte on RV32) is skipped. The record is only a cache: a
 * miss always hashes in full.
 *
 * What makes a hit (all of them):
 *   - the same process asks (fpr_current_pid)
 *   - the same archive object and length, and the same section extents
 *   - the same claimed digests (the strings the check compared against)
 *   - the same CONTENT: a 64-bit fingerprint of every byte the digests cover
 *     (IMAGE, RELOC, IMPORT), so a buffer whose address and edges match but
 *     whose bytes changed (a reused arena turn, an in-place update) misses.
 *     The fingerprint is a few instructions a byte, not a second SHA-256; it
 *     only has to tell "unchanged since the check" from "changed", and the
 *     checked bytes are the caller's own.
 * Lifetime: every check and every placement takes the record out first
 * (imgcache_take), whatever it then decides, so an entry left by a check
 * whose launch failed is gone at the next check or placement, and a hit is
 * used once.
 * Pure C with no runtime dependency, so tests/host/imgcache_check.c tests it. */
#ifndef QOS_LOADER_IMGCACHE_H
#define QOS_LOADER_IMGCACHE_H
#include <stdint.h>
#include <stddef.h>

typedef struct imgcache {
  int valid;
  uintptr_t pid;
  const void *qa;
  uintptr_t qa_len;
  uintptr_t ext[6];
  uint32_t fp[2];
  unsigned char sha[64], relsha[64];
} imgcache_t;

/* two independent 32-bit lanes over little-endian words: 32-bit multiplies
 * only, so RV32 needs no 64-bit libcall */
static inline void imgcache_fp(uint32_t fp[2], const unsigned char *p, uintptr_t n) {
  uint32_t a = fp[0], b = fp[1];
  uintptr_t i = 0;
  for (; i + 4 <= n; i += 4) {
    uint32_t w = (uint32_t)p[i] | (uint32_t)p[i + 1] << 8 | (uint32_t)p[i + 2] << 16 | (uint32_t)p[i + 3] << 24;
    a = (a ^ w) * 0x9E3779B1u;
    a ^= a >> 15;
    b = (b + w) * 0x85EBCA77u;
    b = (b << 13) | (b >> 19);
  }
  for (; i < n; i++) {
    a = (a ^ p[i]) * 0x9E3779B1u;
    b = (b + p[i]) * 0x85EBCA77u;
  }
  /* the length, so a range that moved between sections differs */
  a ^= (uint32_t)n; b += (uint32_t)n * 0xC2B2AE35u;
  fp[0] = a; fp[1] = b;
}

/* the record a check of these bytes would leave */
static inline void imgcache_key(imgcache_t *k, uintptr_t pid, const void *qa, const unsigned char *bytes,
                                uintptr_t qa_len, const uintptr_t ext[6], const unsigned char *sha,
                                const unsigned char *relsha) {
  k->valid = 1;
  k->pid = pid;
  k->qa = qa;
  k->qa_len = qa_len;
  for (int i = 0; i < 6; i++) k->ext[i] = ext[i];
  k->fp[0] = 0x6A09E667u; k->fp[1] = 0xBB67AE85u;
  for (int i = 0; i < 6; i += 2) imgcache_fp(k->fp, bytes + ext[i], ext[i + 1]);
  for (int i = 0; i < 64; i++) { k->sha[i] = sha[i]; k->relsha[i] = relsha[i]; }
}

static inline int imgcache_same(const imgcache_t *a, const imgcache_t *b) {
  if (!a->valid || !b->valid || a->pid != b->pid || a->qa != b->qa || a->qa_len != b->qa_len) return 0;
  if (a->fp[0] != b->fp[0] || a->fp[1] != b->fp[1]) return 0;
  for (int i = 0; i < 6; i++) if (a->ext[i] != b->ext[i]) return 0;
  for (int i = 0; i < 64; i++) if (a->sha[i] != b->sha[i] || a->relsha[i] != b->relsha[i]) return 0;
  return 1;
}

/* move the record out (the caller holds the lock): the cache is empty after */
static inline imgcache_t imgcache_take(imgcache_t *c) {
  imgcache_t r = *c;
  c->valid = 0;
  return r;
}
#endif
