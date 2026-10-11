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
#include <fcntl.h>
#include <limits.h>
#include <unistd.h>

static char g_path[192];

void qosp_store_bind(const char *app_id) {
  /* Directory creation belongs to the checked durable append, not bind. */
  int n = snprintf(g_path, sizeof g_path, "qos-store/%s.kv", app_id);
  if (n < 0 || (size_t)n >= sizeof g_path) g_path[0] = 0;
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
    if (plen != sizeof(qos_plugin_t)) { snprintf(out, outcap, "tag 4 takes a qos_plugin_t (abi v13)"); pthread_mutex_unlock(&store_mu); return -1; }
    int64_t r = qosp_load_plugin((const qos_plugin_t *)pay, out, outcap);
    pthread_mutex_unlock(&store_mu);
    return r;
  }
  if (tag == 8) { /* unload-plugin (QOS_SYS_UNLOADQA): its process ended;
                   * the code pages go back to r-w before the app frees
                   * the block */
    int64_t qosp_unload_plugin(const qos_unload_t *, char *, uint64_t);
    if (plen != sizeof(qos_unload_t)) { snprintf(out, outcap, "tag 8 takes a qos_unload_t (abi v17)"); return -1; }
    pthread_mutex_lock(&store_mu);
    int64_t r = qosp_unload_plugin((const qos_unload_t *)pay, out, outcap);
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
/* The compatibility format has framing, not checksums. This detects malformed
 * headers/delimiters and EOF-truncated tails; it cannot detect arbitrary payload
 * bit rot. Only a trailing record interrupted at EOF may be removed. */
#define STORE_OFF_MAX ((uint64_t)(sizeof(off_t) >= 8 ? INT64_MAX : INT32_MAX))
typedef struct { uint64_t end, bytes; int torn; } store_scan;
static int64_t store_error(char *out, uint64_t cap, int unknown, const char *why) {
  if (out && cap) snprintf(out, (size_t)cap, "storage%s: %s", unknown ? " outcome unknown" : "", why);
  return unknown ? -5 : -1;
}
static int read_at(int fd, char *dst, uint64_t n, uint64_t off) {
  while (n) {
    size_t take = n > (uint64_t)SSIZE_MAX ? (size_t)SSIZE_MAX : (size_t)n;
    ssize_t got = pread(fd, dst, take, (off_t)off);
    if (got < 0 && errno == EINTR) continue;
    if (got <= 0) return -1;
    dst += got; off += (uint64_t)got; n -= (uint64_t)got;
  }
  return 0;
}
static int scan_store(int fd, uint64_t tag, char *out, uint64_t cap, store_scan *scan) {
  struct stat st;
  if (fstat(fd, &st) < 0 || !S_ISREG(st.st_mode) || st.st_size < 0) return -1;
  uint64_t size = (uint64_t)st.st_size, pos = 0, seq = 0, n = 0;
  int full = 0;
  *scan = (store_scan){0, 0, 0};
  while (pos < size) {
    uint64_t start = pos, len = 0;
    unsigned digits = 0;
    int leading_zero = 0, terminated = 0;
    while (pos < size) {
      char c;
      if (read_at(fd, &c, 1, pos++) < 0) return -1;
      if (c == '\n') { terminated = 1; break; }
      if (c < '0' || c > '9' || digits >= 20 || (digits && leading_zero)) return -1;
      if (!digits) leading_zero = c == '0';
      unsigned digit = (unsigned)(c - '0');
      if (len > (STORE_OFF_MAX - digit) / 10) return -1;
      len = len * 10 + digit; digits++;
    }
    if (!digits) return -1;
    if (!terminated || len >= size - pos) {
      scan->end = start; scan->bytes = n; scan->torn = 1;
      return full ? -2 : 0;
    }
    char delimiter;
    if (read_at(fd, &delimiter, 1, pos + len) < 0 || delimiter != '\n') return -1;
    if (!full && tag == 3) {
      if (len > cap - n) full = 1;
      else { if (len && read_at(fd, out + n, len, pos) < 0) return -1; n += len; }
    }
    if (!full && tag == 5) {
      char record[96];
      int count = snprintf(record, sizeof record, "%llu %llu %llu\n",
                           (unsigned long long)seq, (unsigned long long)pos,
                           (unsigned long long)len);
      if (count < 0 || (size_t)count >= sizeof record) return -1;
      if ((uint64_t)count > cap - n) full = 1;
      else { memcpy(out + n, record, (size_t)count); n += (uint64_t)count; }
    }
    pos += len + 1; seq++;
    scan->end = pos;
  }
  scan->bytes = n;
  return full ? -2 : 0;
}
static ssize_t store_write(int fd, const char *src, size_t n) {
#ifdef QOS_STORE_TEST
  static uint64_t written;
  const char *limit_text = getenv("QOS_STORE_TEST_WRITE_LIMIT");
  if (limit_text) {
    uint64_t limit = strtoull(limit_text, 0, 10);
    if (written >= limit) { errno = EIO; return -1; }
    if (n > limit - written) n = (size_t)(limit - written);
  }
  ssize_t count = write(fd, src, n);
  if (count > 0) written += (uint64_t)count;
  return count;
#else
  return write(fd, src, n);
#endif
}
static int write_all(int fd, const char *src, uint64_t n) {
  while (n) {
    size_t take = n > (uint64_t)SSIZE_MAX ? (size_t)SSIZE_MAX : (size_t)n;
    ssize_t count = store_write(fd, src, take);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return -1;
    src += count; n -= (uint64_t)count;
  }
  return 0;
}
static int store_sync(int fd) {
#ifdef QOS_STORE_TEST
  static unsigned long ordinal;
  const char *delay = getenv("QOS_STORE_TEST_SYNC_DELAY_US");
  if (delay) {
    uint64_t us = strtoull(delay, 0, 10);
    struct timespec ts = { (time_t)(us / 1000000ull),
                           (long)((us % 1000000ull) * 1000ull) };
    while (nanosleep(&ts, &ts) < 0 && errno == EINTR) {}
  }
  const char *fail = getenv("QOS_STORE_TEST_FAIL_SYNC_AT");
  if (fail && ++ordinal == strtoul(fail, 0, 10)) { errno = EIO; return -1; }
#endif
  int rc;
  do { rc = fsync(fd); } while (rc < 0 && errno == EINTR);
  return rc;
}
static int store_close(int fd) {
  int rc = close(fd); /* do not retry close(EINTR): the fd may be released */
#ifdef QOS_STORE_TEST
  static unsigned long ordinal;
  const char *fail = getenv("QOS_STORE_TEST_FAIL_CLOSE_AT");
  if (fail && ++ordinal == strtoul(fail, 0, 10)) { errno = EIO; return -1; }
#endif
  return rc;
}
static int64_t append_store(const char *pay, uint64_t plen, char *out, uint64_t cap) {
  if ((plen && !pay) || plen > SIZE_MAX || plen > STORE_OFF_MAX) return store_error(out, cap, 0, "invalid payload length");
  int parent = -1, dir = -1, fd = -1, bad = 1, malformed = 0;
  const char *why = "cannot open store directories";
  parent = open(".", O_RDONLY | O_DIRECTORY);
  if (parent < 0) goto done;
  if (mkdirat(parent, "qos-store", 0755) < 0 && errno != EEXIST) goto done;
  dir = openat(parent, "qos-store", O_RDONLY | O_DIRECTORY);
  if (dir < 0) goto done;
  fd = open(g_path, O_RDWR | O_CREAT | O_APPEND, 0644);
  if (fd < 0) { why = "cannot open store file"; goto done; }
  store_scan scan;
  if (scan_store(fd, 0, NULL, 0, &scan) < 0) { why = "malformed record or read failure"; malformed = 1; goto done; }
  char header[32];
  int hn = snprintf(header, sizeof header, "%llu\n", (unsigned long long)plen);
  if (hn <= 0 || (size_t)hn >= sizeof header ||
      scan.end > STORE_OFF_MAX - (uint64_t)hn - 1 ||
      plen > STORE_OFF_MAX - scan.end - (uint64_t)hn - 1) {
    why = "record exceeds file offset bounds"; malformed = 1; goto done;
  }
  if (scan.torn && ftruncate(fd, (off_t)scan.end) < 0) { why = "cannot repair truncated tail"; goto done; }
  if (write_all(fd, header, (uint64_t)hn) < 0 || write_all(fd, pay, plen) < 0 ||
      write_all(fd, "\n", 1) < 0) { why = "append failed"; goto done; }
  if (store_sync(fd) < 0) { why = "file flush failed"; goto done; }
#ifdef F_FULLFSYNC
  int rc;
  do { rc = fcntl(fd, F_FULLFSYNC); } while (rc < 0 && errno == EINTR);
  if (rc < 0) { why = "file hardware flush failed"; goto done; }
#endif
  /* File name, then qos-store's own name in its parent, must be durable too. */
  if (store_sync(dir) < 0 || store_sync(parent) < 0) { why = "directory flush failed"; goto done; }
  bad = 0;
done:
  if (fd >= 0 && store_close(fd) < 0) { why = "file close failed"; bad = 1; malformed = 0; }
  if (dir >= 0 && store_close(dir) < 0) { why = "directory close failed"; bad = 1; malformed = 0; }
  if (parent >= 0 && store_close(parent) < 0) { why = "parent close failed"; bad = 1; malformed = 0; }
  return bad ? store_error(out, cap, !malformed, why) : 0;
}
static int64_t store_call_locked(uint64_t tag, const char *pay, uint64_t plen, char *out,
                                uint64_t outcap) {
  if (!g_path[0]) return -2;
  if (outcap > SIZE_MAX || outcap > INT64_MAX || (outcap && !out)) return -1;
  if (tag == 2) return append_store(pay, plen, out, outcap);
  if (tag == 3 || tag == 5) {
    int fd = open(g_path, O_RDONLY);
    if (fd < 0) return errno == ENOENT ? 0 : store_error(out, outcap, 0, "cannot open store file");
    store_scan scan;
    int bad = scan_store(fd, tag, out, outcap, &scan);
    if (store_close(fd) < 0) bad = -1;
    if (bad == -2) return store_error(out, outcap, 0, "output capacity exceeded");
    return bad < 0 ? store_error(out, outcap, 0, "malformed record or read/close failure") : (int64_t)scan.bytes;
  }
  return -3;
}
