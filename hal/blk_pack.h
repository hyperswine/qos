#include "blk_hash.h"
/* Pack the part of a two-record write that follows its first header page. */
static V h_blkPackPair(V first, V header, V second) {
  if (ISINT(first) || TID(first) != T_STR || ISINT(header) || TID(header) != T_STR ||
      ISINT(second) || TID(second) != T_STR) fpr_cpanic("blkPackPair: expected strings");
  const str_t *a = (str_t *)first, *h = (str_t *)header, *b = (str_t *)second;
  if (a->len > 7 * 4096 || h->len > 4096 || !h->len || b->len > 7 * 4096)
    fpr_cpanic("blkPackPair: invalid record size");
  if (!a->len && !b->len) return header;
  uw header_at = (a->len + 4095) & ~(uw)4095;
  uw payload_at = header_at + (b->len ? 4096 : h->len);
  uw size = payload_at + b->len;
  if (size > 7 * 4096) fpr_cpanic("blkPackPair: batch exceeds eight pages");
  str_t *out = (str_t *)fpr_alloc(sizeof(str_t) + size);
  out->tid = T_STR; out->var = 0; out->len = size;
  __builtin_memcpy(out->bytes, a->bytes, a->len);
  __builtin_memset(out->bytes + a->len, 0, header_at - a->len);
  __builtin_memcpy(out->bytes + header_at, h->bytes, h->len);
  __builtin_memset(out->bytes + header_at + h->len, 0, payload_at - header_at - h->len);
  __builtin_memcpy(out->bytes + payload_at, b->bytes, b->len);
  return (V)out;
}
FPR_FN(fpr_g_blkPackPair, h_blkPackPair, 3);

/* QLog 31-polynomial chunk hash mod 1e9+7 over s[off..off+len), seeded with
 * acc: the fold of qlog.fpr's hashByte (blk_hash.h), without per-byte FP-RISC
 * recursion and with no 64-bit division per byte. */
static V h_blkHashSlice(V sv, V offv, V lenv, V accv) {
  if (ISINT(sv) || TID(sv) != T_STR || !ISINT(offv) || !ISINT(lenv) || !ISINT(accv))
    fpr_cpanic("blkHashSlice: expected (String, Int, Int, Int)");
  const str_t *s = (str_t *)sv;
  sw off = UNTAG(offv), len = UNTAG(lenv);
  if (off < 0 || len < 0 || (uw)off > s->len || (uw)len > s->len - (uw)off)
    fpr_cpanic("blkHashSlice: slice out of bounds");
  if (!len) return accv; /* nothing folded: the seed as given */
  uint32_t acc = blk_hash_bytes((uint64_t)(sw)UNTAG(accv), (const uint8_t *)s->bytes + (uw)off, (uw)len);
  return TAG((sw)acc);
}
FPR_FN(fpr_g_blkHashSlice, h_blkHashSlice, 4);

/* Adaptive I/O poll backoff (10 -> 25 -> 50 -> 100 -> 200 us) shared by
 * native virtio-blk and portable disk_wait. */
static inline uw blk_next_sleep_us(uw sleep_us) {
  return sleep_us < 25 ? 25 : (sleep_us < 50 ? 50 : (sleep_us < 100 ? 100 : 200));
}
