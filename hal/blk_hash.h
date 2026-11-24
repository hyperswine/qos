/* blk_hash.h -- QLog's chunk hash in C (blk_pack.h's blkHashSlice): the
 * 31-polynomial mod p = 1e9+7 over bytes, the same fold as qlog.fpr's
 * hashByte and mkdisk.sol, so a disk hashes the same on every target.
 *
 * On a 32-bit target a 64-bit `% p` is a libcall per byte (__umoddi3: 70
 * instructions a byte on rv32imac, gcc 14.2). There the fold uses qlog.fpr's
 * split form in 32-bit arithmetic: with split = floor(p / 31), 31 * split =
 * p - 23, so for acc < p and q = acc / split (0..31)
 *   acc * 31 + b  ==  (acc - q * split) * 31 + b - q * 23   (mod p)
 * and that value lies in [-713, p + 255]; one correction brings it back into
 * [0, p). 18 instructions a byte on rv32imac. A 64-bit target keeps the
 * 64-bit form, where `% p` is a multiply-high (RV64: 16 a byte, the split 20).
 * Pure C, no runtime dependency: tests/host/blkhash_check.c checks the split
 * form against the 64-bit one. */
#ifndef QOS_BLK_HASH_H
#define QOS_BLK_HASH_H
#include <stdint.h>

#define BLK_HASH_P 1000000007u
#define BLK_HASH_SPLIT (BLK_HASH_P / 31u) /* 32258064 */

/* acc must be in [0, p): blk_hash_bytes's own results always are */
static inline uint32_t blk_hash_byte32(uint32_t acc, uint8_t b) {
  uint32_t q = acc / BLK_HASH_SPLIT; /* 0..31 */
  /* (acc - q*split)*31 + b - q*23 == acc*31 + b - q*p exactly, and its true
   * value lies in [-713, p + 255], inside int32: so it is computed in uint32
   * (defined modulo 2^32, where both sides agree) and read back as int32 */
  int32_t raw = (int32_t)(acc * 31u + b - q * BLK_HASH_P);
  if (raw < 0) raw += (int32_t)BLK_HASH_P;
  else if ((uint32_t)raw >= BLK_HASH_P) raw -= (int32_t)BLK_HASH_P;
  return (uint32_t)raw;
}

static inline uint64_t blk_hash_byte64(uint64_t acc, uint8_t b) { return (acc * 31u + b) % BLK_HASH_P; }

/* fold n bytes into acc0 (any value: reduced mod p once, as the 64-bit form
 * would have on its first step) */
static inline uint32_t blk_hash_bytes(uint64_t acc0, const uint8_t *p, uintptr_t n) {
#if UINTPTR_MAX > 0xffffffffu
  uint64_t acc = acc0 % BLK_HASH_P;
  for (uintptr_t i = 0; i < n; i++) acc = blk_hash_byte64(acc, p[i]);
  return (uint32_t)acc;
#else
  uint32_t acc = (uint32_t)(acc0 % BLK_HASH_P);
  for (uintptr_t i = 0; i < n; i++) acc = blk_hash_byte32(acc, p[i]);
  return acc;
#endif
}
#endif
