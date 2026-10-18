/* store_abi.h -- the kv storage channel's size contract, shared by both
 * sides on both targets: the portable host (qos/portable/store.c), the
 * portable app side (qos/appside/entry.c), the native kernel trampoline
 * (loader/process.c) and the native process side (qos/native/proc_entry.c).
 *
 * Results of the storage channel (tags 2 append, 3 replay, 5 index):
 *   >= 0  bytes written to out
 *     -1  refused or failed; the reason is NUL-terminated in out
 *     -2  no disk / no app bound      -3  unknown tag
 *     -5  outcome unknown (an append that may or may not have landed)
 *     -6  QOS_SYS_ENEED: the reply is larger than outcap.  out holds the
 *         byte count it needs, in decimal, NUL-terminated (only when
 *         outcap >= QOS_SYS_NEED_MIN; a smaller buffer gets -1).  The
 *         caller retries with a buffer that large; a replay may have
 *         grown in between, so it may answer -6 again.
 * Before -6, a replay larger than the caller's fixed 256 KiB buffer failed
 * on portable ("output capacity exceeded", data unreadable while appends
 * still succeeded) and was silently TRUNCATED on native.  An older peer
 * that does not know -6 reports it as an ordinary storage error.
 *
 * Limits, the same on both targets: one appended record is at most
 * QOS_KV_PAYLOAD_MAX bytes; a reply (a whole replay) at most
 * QOS_KV_REPLY_MAX, refused by name beyond that. */
#ifndef QOS_STORE_ABI_H
#define QOS_STORE_ABI_H

#define QOS_SYS_ENEED (-6)
#define QOS_SYS_NEED_MIN 24u
#define QOS_KV_PAYLOAD_MAX (4ul << 20)  /* 4 MiB */
#define QOS_KV_REPLY_MAX (16ul << 20)   /* 16 MiB */
#define QOS_KV_REPLY_LIMIT_TEXT "16 MiB"

/* The decimal size a -6 reply left in out (0 when unreadable). */
static inline unsigned long qos_store_need(const char *out, unsigned long cap) {
  unsigned long n = 0, i = 0;
  for (; i < cap && out[i] >= '0' && out[i] <= '9'; i++) {
    if (n > (QOS_KV_REPLY_MAX * 10ul)) return 0;
    n = n * 10 + (unsigned long)(out[i] - '0');
  }
  return i && i < cap && out[i] == 0 ? n : 0;
}
/* Write the -6 answer: the needed size into out.  -1 when out cannot hold
 * the digits (the caller's buffer is too small to be told). */
static inline long qos_store_answer_need(unsigned long need, char *out, unsigned long cap) {
  char d[24];
  int k = 0;
  if (!out || cap < QOS_SYS_NEED_MIN) return -1;
  do { d[k++] = (char)('0' + need % 10); need /= 10; } while (need);
  for (int i = 0; i < k; i++) out[i] = d[k - 1 - i];
  out[k] = 0;
  return QOS_SYS_ENEED;
}

#ifdef QOS_STORE_ABI_RUNTIME
/* App side (after fpr.h): one storage request with a buffer that grows to
 * the reply.  The first try goes to the caller's small buffer; on -6 the
 * reply lands in a fresh String exactly as large as it said it needs (up
 * to four tries, a replay can grow between them).  Returns the final
 * status; *big is the String holding the reply (status >= 0) or the
 * reason (status < 0), or NULL when the small buffer holds it.  The
 * caller owns *big: it wraps it on success, fpr_free()s it on error. */
static sw qos_store_call_grow(sw (*call)(uw, const char *, uw, char *, uw),
                              uw tag, const char *pay, uw plen,
                              char *small, uw smallcap, str_t **big) {
  *big = 0;
  small[0] = 0;
  sw r = call(tag, pay, plen, small, smallcap);
  unsigned long need = r == QOS_SYS_ENEED ? qos_store_need(small, smallcap) : 0;
  for (int tries = 0; r == QOS_SYS_ENEED && tries < 4; tries++) {
    if (!need || need > QOS_KV_REPLY_MAX) break;
    uw cap = need < QOS_SYS_NEED_MIN ? QOS_SYS_NEED_MIN : (uw)need;
    str_t *s = (str_t *)fpr_alloc((V)(sizeof(str_t) + cap));
    s->tid = T_STR; s->var = 0; s->len = 0;
    s->bytes[0] = 0;
    r = call(tag, pay, plen, (char *)s->bytes, cap);
    if (r >= 0) { s->len = (uw)r; *big = s; return r; }
    if (r != QOS_SYS_ENEED) { *big = s; return r; }
    need = qos_store_need((const char *)s->bytes, cap);
    fpr_free((V)s);
  }
  if (r == QOS_SYS_ENEED) {
    const char *why = "storage: reply exceeds the " QOS_KV_REPLY_LIMIT_TEXT " limit";
    uw k = 0;
    while (why[k] && k + 1 < smallcap) { small[k] = why[k]; k++; }
    small[k] = 0;
    return -1;
  }
  return r;
}
/* Ok <the String>, without copying it */
static V qos_store_ok_str(str_t *s) {
  hdr_t *h = (hdr_t *)fpr_alloc((V)(8 + sizeof(uw)));
  h->tid = T_RESULT;
  h->var = 0;
  *(V *)((char *)h + 8) = (V)s;
  return (V)h;
}
#endif
#endif
