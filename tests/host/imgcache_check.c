/* imgcache_check.c -- the launch path's verified-image record
 * (loader/imgcache.h), driven the way loader/process.c check_image drives
 * it: every check and placement takes the record out first; a check that
 * passes stores its key; a placement hits only on an equal key.
 *   cc -O2 -Wall -Wextra imgcache_check.c -o imgcache_check && ./imgcache_check */
#include "../../loader/imgcache.h"
#include <stdio.h>
#include <string.h>

static imgcache_t cache;
static int fails;
#define CHECK(c, what) do { if (!(c)) { printf("FAIL %s (line %d)\n", what, __LINE__); fails++; } } while (0)

static unsigned char qa[8192];
static const uintptr_t ext[6] = {256, 4096, 4352, 1024, 5376, 0};
static unsigned char sha[64], relsha[64];

static void key(imgcache_t *k, uintptr_t pid) { imgcache_key(k, pid, qa, qa, sizeof qa, ext, sha, relsha); }
/* Sys.checkImage: take, (hash), store on success */
static void check(uintptr_t pid, int passes) {
  imgcache_t prev = imgcache_take(&cache), k;
  (void)prev;
  if (!passes) return;
  key(&k, pid);
  cache = k;
}
/* Sys.placeImageAt: take, hit only on an equal key (else hash in full) */
static int place_skips_hash(uintptr_t pid) {
  imgcache_t prev = imgcache_take(&cache), k;
  key(&k, pid);
  return imgcache_same(&prev, &k);
}

int main(void) {
  uint32_t r = 12345;
  for (size_t i = 0; i < sizeof qa; i++) { r = r * 1103515245u + 12345u; qa[i] = (unsigned char)(r >> 16); }
  for (int i = 0; i < 64; i++) { sha[i] = "0123456789abcdef"[i & 15]; relsha[i] = "fedcba9876543210"[i & 15]; }

  /* a valid launch skips the second hash, once */
  check(3, 1);
  CHECK(place_skips_hash(3), "check then place of the same bytes skips the second hash");
  CHECK(!place_skips_hash(3), "the record is used once");

  /* a failed launch (grant refused after the check: no placement) leaves an
   * entry; the next check takes it out whatever it decides */
  check(3, 1);
  check(3, 0); /* the next launch's check fails */
  CHECK(!place_skips_hash(3), "a stale entry does not outlive the next check");

  /* a placement that hashes anyway (a miss) also empties the record */
  check(3, 1);
  (void)place_skips_hash(4); /* another process's placement */
  CHECK(!place_skips_hash(3), "any placement takes the record out");

  /* another process cannot use a check it did not make */
  check(3, 1);
  CHECK(!place_skips_hash(4), "a different process misses");

  /* the same buffer address and edges, different middle bytes: a miss */
  for (uintptr_t sec = 0; sec < 6; sec += 2) {
    if (!ext[sec + 1]) continue;
    uintptr_t mid = ext[sec] + ext[sec + 1] / 2;
    check(3, 1);
    qa[mid] ^= 0x40;
    CHECK(!place_skips_hash(3), "a changed middle byte misses");
    qa[mid] ^= 0x40;
  }
  /* bytes the digests do not cover (between sections) may change */
  check(3, 1);
  qa[100] ^= 1;
  CHECK(place_skips_hash(3), "bytes outside IMAGE/RELOC/IMPORT do not matter");
  qa[100] ^= 1;

  /* every single-bit flip in IMAGE misses (each one tried) */
  int flips = 0, missed = 0;
  for (uintptr_t i = ext[0]; i < ext[0] + ext[1]; i++)
    for (int bit = 0; bit < 8; bit++) {
      check(3, 1);
      qa[i] ^= (unsigned char)(1u << bit);
      flips++; missed += !place_skips_hash(3);
      qa[i] ^= (unsigned char)(1u << bit);
    }
  CHECK(missed == flips, "every bit flip in IMAGE misses");
  /* two swapped words (same multiset of bytes) miss */
  check(3, 1);
  unsigned char t[4]; memcpy(t, qa + 300, 4); memcpy(qa + 300, qa + 304, 4); memcpy(qa + 304, t, 4);
  CHECK(!place_skips_hash(3), "swapped words miss");
  memcpy(t, qa + 300, 4); memcpy(qa + 300, qa + 304, 4); memcpy(qa + 304, t, 4);
  /* a different claimed digest misses */
  check(3, 1);
  sha[10] ^= 1;
  CHECK(!place_skips_hash(3), "a different claimed digest misses");
  sha[10] ^= 1;

  printf("bit flips tried %d, missed %d\n", flips, missed);
  puts(fails ? "imgcache: FAIL" : "imgcache: PASS");
  return fails ? 1 : 0;
}
