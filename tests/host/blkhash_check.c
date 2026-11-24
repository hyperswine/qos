/* blkhash_check.c -- QLog's chunk hash in 32-bit arithmetic (hal/blk_hash.h,
 * what a 32-bit target runs) against the 64-bit reference fold blkHashSlice
 * used before: every byte at the seed edges, random seeds and bytes, and
 * whole random buffers through both the split form and blk_hash_bytes.
 *   cc -O2 -Wall -Wextra blkhash_check.c -o blkhash_check && ./blkhash_check [cases] */
#include "../../hal/blk_hash.h"
#include <stdio.h>
#include <stdlib.h>

static uint64_t ref_bytes(uint64_t acc, const uint8_t *p, uintptr_t n) {
  for (uintptr_t i = 0; i < n; i++) acc = (acc * 31ULL + (uint64_t)p[i]) % 1000000007ULL;
  return acc;
}
static uint64_t rng = 0x9E3779B97F4A7C15ull;
static uint64_t next(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; }

int main(int argc, char **argv) {
  long cases = argc > 1 ? atol(argv[1]) : 50000000L, bad = 0;
  const uint32_t P = BLK_HASH_P;
  /* every byte at the seeds where the split form changes behaviour */
  uint32_t edges[] = {0, 1, 7, BLK_HASH_SPLIT - 1, BLK_HASH_SPLIT, BLK_HASH_SPLIT + 1, 31u * BLK_HASH_SPLIT - 1,
                      31u * BLK_HASH_SPLIT, P - 24, P - 23, P - 2, P - 1};
  for (unsigned e = 0; e < sizeof edges / sizeof edges[0]; e++)
    for (int b = 0; b < 256; b++) {
      uint8_t x = (uint8_t)b;
      if (blk_hash_byte32(edges[e], x) != ref_bytes(edges[e], &x, 1)) bad++;
    }
  /* random single steps over the whole seed range */
  for (long t = 0; t < cases; t++) {
    uint64_t r = next();
    uint32_t acc = (uint32_t)(r % P);
    uint8_t b = (uint8_t)(r >> 40);
    if (blk_hash_byte32(acc, b) != ref_bytes(acc, &b, 1) || blk_hash_byte64(acc, b) != ref_bytes(acc, &b, 1)) bad++;
  }
  /* whole buffers up to two QLog pages, seeded as qlog seeds them (7) */
  static uint8_t buf[8192];
  for (int t = 0; t < 2000; t++) {
    uintptr_t n = (uintptr_t)(next() % sizeof buf);
    for (uintptr_t i = 0; i < n; i++) buf[i] = (uint8_t)next();
    uint64_t seed = t & 1 ? 7 : next() % P;
    uint32_t a32 = (uint32_t)(seed % BLK_HASH_P);
    for (uintptr_t i = 0; i < n; i++) a32 = blk_hash_byte32(a32, buf[i]);
    if (a32 != ref_bytes(seed, buf, n) || blk_hash_bytes(seed, buf, n) != ref_bytes(seed, buf, n)) bad++;
  }
  printf("blkhash: %ld random steps + edges + 2000 buffers, %ld mismatches\n", cases, bad);
  puts(bad ? "blkhash: FAIL" : "blkhash: PASS");
  return bad ? 1 : 0;
}
