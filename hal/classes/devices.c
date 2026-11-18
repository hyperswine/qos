/* devices.c -- the FP-RISC primitives of the INPUT, CLOCK, HOSTFS and AUDIO
 * classes, once for every driver (contracts in input.h, clock.h, hostfs.h,
 * audio.h). A wrong argument TYPE is a programming error (fpr_cpanic). */
#include "fpr.h"
#include "devtable.h"
#include "input.h"
#include "clock.h"
#include "hostfs.h"
#include "audio.h"

static const void *instance(V d, uint16_t cls, uint32_t version, const char *what, void **st) {
  if (ISINT(d) || !d || TID(d) != T_DEVICE) fpr_cpanic("device class: not a Device");
  const devtable_entry_t *e = devtable_entry_of(d);
  if (e->cls != cls || !e->ops) fpr_cpanic(what);
  if (*(const uint32_t *)e->ops != version) fpr_cpanic("device class: driver built for another contract");
  *st = e->state;
  return e->ops;
}
static str_t *is_str(V v) { return !ISINT(v) && v && TID(v) == T_STR ? (str_t *)v : 0; }
static V mkstr(const uint8_t *b, uw n) {
  str_t *s = (str_t *)fpr_alloc(sizeof(str_t) + n);
  s->tid = T_STR; s->var = 0; s->len = n;
  for (uw i = 0; i < n; i++) s->bytes[i] = (char)b[i];
  return (V)s;
}
static V result(int err, V value) {
  V *r = (V *)fpr_alloc(8 + sizeof(uw));
  ((hdr_t *)r)->tid = T_RESULT;
  ((hdr_t *)r)->var = err ? 1 : 0;
  FPR_FLD(r, 0) = value;
  return (V)r;
}
static V err_text(const char *s) {
  uw n = 0;
  while (s[n]) n++;
  return result(1, mkstr((const uint8_t *)s, n));
}

/* ---- input ---- */
static V h_inRead(V d) {
  void *st;
  const qos_input_ops *ops = instance(d, FPR_DEV_INPUT, QOS_INPUT_OPS_VERSION, "inRead: not an input device", &st);
  uint8_t buf[64 * QOS_INPUT_EVENT];
  return mkstr(buf, ops->read(st, buf, sizeof buf));
}

/* ---- clock ---- */
static V h_clkNow(V d) {
  void *st;
  const qos_clock_ops *ops = instance(d, FPR_DEV_CLOCK, QOS_CLOCK_OPS_VERSION, "clkNow: not a clock device", &st);
  char buf[24];
  return mkstr((const uint8_t *)buf, ops->now(st, buf, sizeof buf));
}

/* ---- hostfs ---- */
static V hf_failure(int rc, const uint8_t *reply, uint32_t len) {
  if (rc == 1) return result(1, mkstr(reply, len));
  if (rc == -1) return err_text("hostfs: no host attached");
  if (rc == -2) return err_text("hostfs: the host did not answer in time");
  return err_text("hostfs: the host's answer was longer than asked for");
}
/* READ and LIST: chunks until a short one, into a buffer that doubles */
static V hf_chunks(V d, V pv, uint8_t op, const char *what) {
  void *st;
  const qos_hostfs_ops *ops = instance(d, FPR_DEV_HOSTFS, QOS_HOSTFS_OPS_VERSION, what, &st);
  str_t *path = is_str(pv);
  if (!path) fpr_cpanic("hostfs: path must be a String");
  uw cap = HOSTFS_CHUNK, n = 0;
  uint8_t *acc = (uint8_t *)fpr_alloc(cap);
  uint8_t chunk[HOSTFS_CHUNK];
  for (;;) {
    uint8_t req[6] = {(uint8_t)n, (uint8_t)(n >> 8), (uint8_t)(n >> 16), (uint8_t)(n >> 24),
                      (uint8_t)HOSTFS_CHUNK, (uint8_t)(HOSTFS_CHUNK >> 8)};
    uint32_t len = 0;
    int rc = ops->call(st, op, (const uint8_t *)path->bytes, (uint32_t)path->len, req, 6, chunk, HOSTFS_CHUNK, &len);
    if (rc) return hf_failure(rc, chunk, len);
    if (n + len > cap) {
      while (n + len > cap) cap *= 2;
      uint8_t *grown = (uint8_t *)fpr_alloc(cap);
      for (uw i = 0; i < n; i++) grown[i] = acc[i];
      acc = grown;
    }
    for (uint32_t i = 0; i < len; i++) acc[n + i] = chunk[i];
    n += len;
    if (len < HOSTFS_CHUNK) return result(0, mkstr(acc, n));
  }
}
static V h_hfRead(V d, V p) { return hf_chunks(d, p, HOSTFS_READ, "hfRead: not a hostfs device"); }
static V h_hfList(V d, V p) { return hf_chunks(d, p, HOSTFS_LIST, "hfList: not a hostfs device"); }
/* WRITE and APPEND: the first piece replaces (or appends), the rest append */
static V hf_put(V d, V pv, V sv, uint8_t op, const char *what) {
  void *st;
  const qos_hostfs_ops *ops = instance(d, FPR_DEV_HOSTFS, QOS_HOSTFS_OPS_VERSION, what, &st);
  str_t *path = is_str(pv), *s = is_str(sv);
  if (!path || !s) fpr_cpanic("hostfs: path and bytes must be Strings");
  uw off = 0;
  do {
    uw k = s->len - off > 0xffff ? 0xffff : s->len - off;
    uint8_t reply[256];
    uint32_t len = 0;
    int rc = ops->call(st, off ? HOSTFS_APPEND : op, (const uint8_t *)path->bytes, (uint32_t)path->len,
                       (const uint8_t *)s->bytes + off, (uint32_t)k, reply, sizeof reply, &len);
    if (rc) return hf_failure(rc, reply, len);
    off += k;
  } while (off < s->len);
  return result(0, mkstr(0, 0));
}
static V h_hfWrite(V d, V p, V s) { return hf_put(d, p, s, HOSTFS_WRITE, "hfWrite: not a hostfs device"); }
static V h_hfAppend(V d, V p, V s) { return hf_put(d, p, s, HOSTFS_APPEND, "hfAppend: not a hostfs device"); }

/* ---- audio ---- */
static V h_audTone(V d, V f, V ms) {
  void *st;
  const qos_audio_ops *ops = instance(d, FPR_DEV_AUDIO, QOS_AUDIO_OPS_VERSION, "audTone: not an audio device", &st);
  if (!ISINT(f) || !ISINT(ms) || UNTAG(f) < 0 || UNTAG(ms) < 0) fpr_cpanic("audTone: frequency and duration must be non-negative Ints");
  return TAG((sw)ops->tone(st, (uint32_t)UNTAG(f), (uint32_t)UNTAG(ms)));
}

FPR_FN(fpr_g_inRead, h_inRead, 1);
FPR_FN(fpr_g_clkNow, h_clkNow, 1);
FPR_FN(fpr_g_hfRead, h_hfRead, 2);
FPR_FN(fpr_g_hfList, h_hfList, 2);
FPR_FN(fpr_g_hfWrite, h_hfWrite, 3);
FPR_FN(fpr_g_hfAppend, h_hfAppend, 3);
FPR_FN(fpr_g_audTone, h_audTone, 3);
