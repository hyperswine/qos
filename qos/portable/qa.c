/* qa.c -- the QAR2 container + manifest-TOML-subset reader (qa.h).
 * Mirrors the byte layout and rules in docs/QA-FORMAT.md; the FPRISC
 * launcher in system.fpr and this file must keep agreeing, so any
 * format change lands in both (and in tools/mkqa.py). */
#include "qa.h"
#include "hostlog.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int qa_parse_owned(qa_t *qa);
static int fail(const char *why) {
  qos_hostlog("qa: %s", why);
  return -1;
}


/* ---- sha256 (FIPS 180-4), compact host-side implementation --------- */
static const uint32_t sha_k[64] = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
#define ROR(x,n) (((x)>>(n))|((x)<<(32-(n))))
static void sha_block(uint32_t h[8], const unsigned char *p) {
  uint32_t w[64], a,b,c,d,e,f,g,hh;
  for (int i = 0; i < 16; i++)
    w[i] = (uint32_t)p[4*i]<<24 | (uint32_t)p[4*i+1]<<16 | (uint32_t)p[4*i+2]<<8 | p[4*i+3];
  for (int i = 16; i < 64; i++) {
    uint32_t s0 = ROR(w[i-15],7) ^ ROR(w[i-15],18) ^ (w[i-15]>>3);
    uint32_t s1 = ROR(w[i-2],17) ^ ROR(w[i-2],19) ^ (w[i-2]>>10);
    w[i] = w[i-16] + s0 + w[i-7] + s1;
  }
  a=h[0]; b=h[1]; c=h[2]; d=h[3]; e=h[4]; f=h[5]; g=h[6]; hh=h[7];
  for (int i = 0; i < 64; i++) {
    uint32_t s1 = ROR(e,6) ^ ROR(e,11) ^ ROR(e,25);
    uint32_t ch = (e & f) ^ (~e & g);
    uint32_t t1 = hh + s1 + ch + sha_k[i] + w[i];
    uint32_t s0 = ROR(a,2) ^ ROR(a,13) ^ ROR(a,22);
    uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
    uint32_t t2 = s0 + mj;
    hh=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
  }
  h[0]+=a; h[1]+=b; h[2]+=c; h[3]+=d; h[4]+=e; h[5]+=f; h[6]+=g; h[7]+=hh;
}
void qosp_sha256(const unsigned char *msg, uint64_t n, unsigned char out[32]) {
  uint32_t h[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                   0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  uint64_t i = 0;
  for (; i + 64 <= n; i += 64) sha_block(h, msg + i);
  unsigned char tail[128] = {0};
  uint64_t r = n - i;
  memcpy(tail, msg + i, (size_t)r);
  tail[r] = 0x80;
  uint64_t tl = (r + 9 <= 64) ? 64 : 128;
  uint64_t bits = n * 8;
  for (int k = 0; k < 8; k++) tail[tl - 1 - k] = (unsigned char)(bits >> (8 * k));
  sha_block(h, tail);
  if (tl == 128) sha_block(h, tail + 64);
  for (int k = 0; k < 8; k++) {
    out[4*k]   = (unsigned char)(h[k] >> 24);
    out[4*k+1] = (unsigned char)(h[k] >> 16);
    out[4*k+2] = (unsigned char)(h[k] >> 8);
    out[4*k+3] = (unsigned char)(h[k]);
  }
}

/* verify the LOAD section's `sha <hex>` line against IMAGE; absent
 * line = no check (stated in the format doc).  Returns 0 ok / -1. */
static int qa_sha_check(const qa_t *qa) {
  const char *p = (const char *)qa->load, *end = p + qa->load_len;
  while (p < end) {
    const char *nl = memchr(p, '\n', (size_t)(end - p));
    const char *le = nl ? nl : end;
    if (le - p >= 4 + 64 && !strncmp(p, "sha ", 4)) {
      unsigned char want[32], got[32];
      for (int i = 0; i < 32; i++) {
        int hi, lo;
        char a = p[4 + 2*i], b = p[5 + 2*i];
        hi = a >= 'a' ? a - 'a' + 10 : a - '0';
        lo = b >= 'a' ? b - 'a' + 10 : b - '0';
        want[i] = (unsigned char)((hi << 4) | lo);
      }
      qosp_sha256(qa->img, qa->img_len, got);
      return memcmp(want, got, 32) ? -1 : 0;
    }
    if (!nl) break;
    p = nl + 1;
  }
  return 0; /* no sha line: nothing claimed, nothing to refuse */
}

/* one "NAME OFFSET LENGTH" table line; returns chars consumed or 0 */
static int table_line(const char *p, const char *end, char *name, uint64_t *off,
                      uint64_t *len) {
  const char *q = p;
  int n = 0;
  while (q < end && *q != ' ' && *q != '\n' && n < 31) name[n++] = *q++;
  name[n] = 0;
  if (q >= end || *q != ' ') return 0;
  *off = strtoull(q + 1, (char **)&q, 10);
  if (q >= end || *q != ' ') return 0;
  *len = strtoull(q + 1, (char **)&q, 10);
  if (q >= end || *q != '\n') return 0;
  return (int)(q + 1 - p);
}

/* a fixed-format identity field (name, id, abi, ...).  One that does not
 * fit is REFUSED, never cut: the id keys the app's store, and two ids
 * sharing a truncated prefix would silently share it. */
static int copy_tok(char *dst, uint64_t cap, const char *src, uint64_t n) {
  if (n >= cap) return -1;
  memcpy(dst, src, n);
  dst[n] = 0;
  return 0;
}

/* the manifest: `key = value` lines, values "quoted" or bare;
 * [section.sub] opens a table (docs/QA-FORMAT.md's exact subset) */
/* an owned, NUL-terminated copy of a manifest token, whatever its length */
static char *dup_tok(const char *src, uint64_t n) {
  char *d = malloc((size_t)n + 1);
  if (!d) return 0;
  memcpy(d, src, (size_t)n);
  d[n] = 0;
  return d;
}

static int parse_manifest(qa_t *qa) {
  const char *p = (const char *)qa->manifest;
  const char *end = p + qa->manifest_len;
  int in_req = 0, in_opt = 0;
  while (p < end) {
    const char *nl = memchr(p, '\n', (size_t)(end - p));
    const char *le = nl ? nl : end;
    /* trim */
    while (p < le && (*p == ' ' || *p == '\t')) p++;
    if (p < le && *p == '[') {
      in_req = (le - p >= 22) && !strncmp(p, "[permissions.required]", 22);
      in_opt = (le - p >= 22) && !strncmp(p, "[permissions.optional]", 22);
    } else if (p < le && *p != '#') {
      const char *eq = memchr(p, '=', (size_t)(le - p));
      if (eq) {
        const char *k = p, *ke = eq;
        while (ke > k && (ke[-1] == ' ' || ke[-1] == '\t')) ke--;
        const char *v = eq + 1;
        while (v < le && (*v == ' ' || *v == '\t')) v++;
        const char *ve = le;
        while (ve > v && (ve[-1] == ' ' || ve[-1] == '\t' || ve[-1] == '\r')) ve--;
        /* unquote both sides if quoted */
        uint64_t kn = (uint64_t)(ke - k), vn = (uint64_t)(ve - v);
        if (kn >= 2 && k[0] == '"' && k[kn - 1] == '"') { k++; kn -= 2; }
        if (vn >= 2 && v[0] == '"' && v[vn - 1] == '"') { v++; vn -= 2; }
        if (in_req || in_opt) {
          if (qa->nperms == qa->perms_cap) {
            int cap = qa->perms_cap ? qa->perms_cap * 2 : 8;
            qa_perm_t *np = realloc(qa->perms, (size_t)cap * sizeof *np);
            if (!np) return fail("out of memory (permissions)");
            qa->perms = np;
            qa->perms_cap = cap;
          }
          qa_perm_t *pm = &qa->perms[qa->nperms];
          pm->url = dup_tok(k, kn);
          pm->mode = dup_tok(v, vn);
          pm->required = in_req;
          pm->granted = 0;
          qa->nperms++; /* counted even half-built, so qa_free releases it */
          if (!pm->url || !pm->mode) return fail("out of memory (permissions)");
        } else if (kn == 4 && !strncmp(k, "name", 4))
          { if (copy_tok(qa->name, sizeof qa->name, v, vn)) return fail("manifest: name is too long"); }
        else if (kn == 2 && !strncmp(k, "id", 2))
          { if (copy_tok(qa->id, sizeof qa->id, v, vn)) return fail("manifest: id is too long"); }
        else if (kn == 8 && !strncmp(k, "loadMode", 8))
          { if (copy_tok(qa->load_mode, sizeof qa->load_mode, v, vn)) return fail("manifest: load_mode is too long"); }
        else if (kn == 3 && !strncmp(k, "abi", 3))
          { if (copy_tok(qa->abi, sizeof qa->abi, v, vn)) return fail("manifest: abi is too long"); }
        else if (kn == 5 && !strncmp(k, "shell", 5))
          { if (copy_tok(qa->shell, sizeof qa->shell, v, vn)) return fail("manifest: shell is too long"); }
      }
    }
    if (!nl) break;
    p = nl + 1;
  }
  return 0;
}

int qa_parse(const unsigned char *bytes, uint64_t len, qa_t *qa) {
  memset(qa, 0, sizeof *qa);
  if (!bytes || len == 0) return fail("empty archive");
  /* own a copy: (a) table_line's strtoull wants a trailing NUL, and
   * (b) the caller's buffer may be an app-side String whose ARC life
   * ends the moment the syscall returns -- the parse must not borrow */
  qa->bytes = malloc((size_t)len + 1);
  if (!qa->bytes) return fail("out of memory");
  memcpy(qa->bytes, bytes, (size_t)len);
  qa->bytes[len] = 0;
  qa->len = len;
  return qa_parse_owned(qa);
}

/* parse the archive qa->bytes already owns (NUL-terminated at len) */
static int qa_parse_owned(qa_t *qa) {
  const char *p = (const char *)qa->bytes;
  const char *end = p + qa->len;
  if (qa->len < 5 || memcmp(p, "QAR2\n", 5)) return fail("bad magic (not QAR2)");
  p += 5;
  /* the section table: one line per section, blank line ends it */
  struct { char name[32]; uint64_t off, len; } secs[8];
  int nsecs = 0;
  while (p < end && *p != '\n') {
    if (nsecs >= 8) return fail("too many sections");
    int c = table_line(p, end, secs[nsecs].name, &secs[nsecs].off, &secs[nsecs].len);
    if (!c) return fail("malformed section-table line");
    nsecs++;
    p += c;
  }
  if (p >= end) return fail("truncated: no blank line after table");
  p++; /* the blank line: payloads start here */
  uint64_t pay0 = (uint64_t)(p - (const char *)qa->bytes);

  for (int i = 0; i < nsecs; i++) {
    if (pay0 + secs[i].off + secs[i].len > qa->len)
      return fail("section runs past end of archive");
    const unsigned char *sp = qa->bytes + pay0 + secs[i].off;
    if (!strcmp(secs[i].name, "MANIFEST")) {
      qa->manifest = sp;
      qa->manifest_len = secs[i].len;
    } else if (!strcmp(secs[i].name, "LOAD")) {
      qa->load = sp;
      qa->load_len = secs[i].len;
    } else if (!strcmp(secs[i].name, "IMAGE")) {
      qa->img = sp;
      qa->img_len = secs[i].len;
    } /* unknown sections ignored by design */
  }
  if (!qa->manifest) return fail("no MANIFEST section");
  if (!qa->load) return fail("no LOAD section");
  /* IMAGE may be empty (placeholder .qa); qaimg refuses memsz 0 with
   * a named reason if someone tries to LOAD one */
  if (qa_sha_check(qa)) return fail("IMAGE sha256 mismatch (corrupt archive)");
  if (parse_manifest(qa)) return -1;
  if (!qa->id[0]) return fail("manifest has no id");
  return 0;
}

void qa_free(qa_t *qa) {
  free(qa->bytes);
  qa->bytes = 0;
  for (int i = 0; i < qa->nperms; i++) {
    free(qa->perms[i].url);
    free(qa->perms[i].mode);
  }
  free(qa->perms);
  qa->perms = 0;
  qa->nperms = qa->perms_cap = 0;
}
