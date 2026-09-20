/* store.c -- qosp's System.qa-analogue storage trampoline.
 *
 * Tag-compatible with the virt process model's channel (process.c /
 * proc_entry.c): tag 2 = kv append, tag 3 = kv replay, and capability
 * scoping is enforced HERE, structurally -- the app never names a
 * path; the host derives qos-store/<id>.kv from the id it bound at
 * launch, exactly the way System.qa rewrites the relative "kv" url to
 * apps/<id>/<id>.kv.  The append-only discipline maps onto O_APPEND:
 * records go on the end, replay returns the whole log, readers fold.
 *
 * A record is the payload's bytes, length-prefixed ("%lu\n" + bytes +
 * "\n") so binary payloads survive round trips; replay concatenates
 * the raw record payloads in append order, which is what the FPRISC
 * kv fold consumes. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static char g_path[192];

void qosp_store_bind(const char *app_id) {
  mkdir("qos-store", 0755); /* best-effort; open errors are the real gate */
  snprintf(g_path, sizeof g_path, "qos-store/%s.kv", app_id);
}

#include <pthread.h>
#include <errno.h>
#include <time.h>
#include "qos_abi.h" /* tag 4 carries a qos_plugin_t */
static pthread_mutex_t store_mu = PTHREAD_MUTEX_INITIALIZER;
static int64_t store_call_locked(uint64_t tag, const char *pay,
                                 uint64_t plen, char *out, uint64_t outcap);
int64_t qosp_load_plugin(const qos_plugin_t *pl, char *err,
                               uint64_t errcap);

int64_t qosp_store_call(uint64_t tag, const char *pay, uint64_t plen,
                        char *out, uint64_t outcap) {
  if (tag == 4) { /* load-plugin (qos_abi.h QOS_SYS_LOADQA): the payload
                   * IS the .qa container bytes -- the app read them
                   * off qosp.disk (mods/qlog over the blk tier), so
                   * name->bytes resolution stays FPRISC's and the
                   * host filesystem never enters the load path.  The
                   * shared address space makes this a pointer pass,
                   * the same discipline gfx_render uses. */
    pthread_mutex_lock(&store_mu);
    if (plen != sizeof(qos_plugin_t)) { snprintf(out, outcap, "tag 4 takes a qos_plugin_t (abi v13)"); return -1; }
    int64_t r = qosp_load_plugin((const qos_plugin_t *)pay, out, outcap);
    pthread_mutex_unlock(&store_mu);
    return r;
  }
  if (tag == 7) { /* compile: bridge to the host fpr compiler server
                   * over its unix socket (compile.c).  No store lock:
                   * a compile can take seconds, and it touches no kv
                   * state -- same reasoning as sleep below. */
    int64_t qosp_compile_call(const char *, uint64_t, char *, uint64_t);
    return qosp_compile_call(pay, plen, out, outcap);
  }
  if (tag == 6) { /* sleep_us: payload = decimal microseconds text.
                   * No store lock: sleeping under it would starve
                   * every other hart's kv traffic for the duration. */
    char buf[24];
    uint64_t n = plen < sizeof buf - 1 ? plen : sizeof buf - 1;
    memcpy(buf, pay, n);
    buf[n] = 0;
    unsigned long long us = strtoull(buf, 0, 10);
    struct timespec ts = { (time_t)(us / 1000000ull),
                           (long)((us % 1000000ull) * 1000ull) };
    while (nanosleep(&ts, &ts) == -1 && errno == EINTR) {}
    return 0;
  }
  /* v2: any hart thread may persist; the kv file wants one writer */
  pthread_mutex_lock(&store_mu);
  int64_t r = store_call_locked(tag, pay, plen, out, outcap);
  pthread_mutex_unlock(&store_mu);
  return r;
}
static int64_t store_call_locked(uint64_t tag, const char *pay, uint64_t plen, char *out,
                        uint64_t outcap) {
  if (!g_path[0]) return -2; /* no app bound: "no disk" to the app */
  if (tag == 2) { /* append */
    FILE *f = fopen(g_path, "ab");
    if (!f) return -1;
    fprintf(f, "%llu\n", (unsigned long long)plen);
    fwrite(pay, 1, plen, f);
    fputc('\n', f);
    fclose(f);
    return 0;
  }
  if (tag == 3) { /* replay: concatenated record payloads */
    FILE *f = fopen(g_path, "rb");
    if (!f) return 0; /* nothing appended yet: empty replay */
    uint64_t n = 0;
    char line[32];
    while (fgets(line, sizeof line, f)) {
      unsigned long long rl = strtoull(line, 0, 10);
      if (n + rl > outcap) break; /* honest truncation at capacity */
      if (fread(out + n, 1, rl, f) != rl) break;
      n += rl;
      fgetc(f); /* the record's trailing newline */
    }
    fclose(f);
    return (int64_t)n;
  }
  if (tag == 5) {
  /* tag 5: the record INDEX -- one "seq off len" line per record, the
   * append log's own structure rather than its flattened payloads
   * (tag 3).  This is what makes the disk visible AS a delta log:
   * every append is a record at a byte offset that never moves. */
    FILE *f = fopen(g_path, "rb");
    if (!f) return 0;
    uint64_t n = 0, off = 0, seq = 0;
    char line[32];
    while (fgets(line, sizeof line, f)) {
      unsigned long long rl = strtoull(line, 0, 10);
      uint64_t hdr = (uint64_t)strlen(line);
      char rec[64];
      int rn = snprintf(rec, sizeof rec, "%llu %llu %llu\n",
                        (unsigned long long)seq, (unsigned long long)(off + hdr),
                        rl);
      if (n + (uint64_t)rn > outcap) break;
      memcpy(out + n, rec, (size_t)rn);
      n += (uint64_t)rn;
      if (fseek(f, (long)rl + 1, SEEK_CUR)) break;
      off += hdr + rl + 1;
      seq++;
    }
    fclose(f);
    return (int64_t)n;
  }
  return -3;
}
