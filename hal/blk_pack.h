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
