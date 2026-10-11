/* Standalone driver around the real compatibility store. Each invocation is
 * a fresh process; store_check.py supplies disk snapshots and fault positions. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int read_interrupt, write_interrupt, sync_interrupt;
static char trace_kind(int fd) {
  struct stat st, parent;
  if (fstat(fd, &st) || stat(".", &parent)) return '?';
  if (S_ISREG(st.st_mode)) return 'F';
  return st.st_dev == parent.st_dev && st.st_ino == parent.st_ino ? 'P' : 'D';
}
static ssize_t observed_pread(int fd, void *p, size_t n, off_t off) {
  if (getenv("QOS_STORE_TEST_EINTR_READ") && !read_interrupt++) { errno = EINTR; return -1; }
  return pread(fd, p, n, off);
}
static ssize_t observed_write(int fd, const void *p, size_t n) {
  if (getenv("QOS_STORE_TEST_EINTR_WRITE") && !write_interrupt++) { errno = EINTR; return -1; }
  return write(fd, p, n);
}
static int observed_fsync(int fd) {
  if (getenv("QOS_STORE_TEST_TRACE")) fputc(trace_kind(fd), stderr);
  if (getenv("QOS_STORE_TEST_EINTR_SYNC") && !sync_interrupt++) { errno = EINTR; return -1; }
  return fsync(fd);
}
static int observed_close(int fd) {
  char kind = trace_kind(fd);
  int rc = close(fd);
  if (getenv("QOS_STORE_TEST_TRACE")) fputc(kind + ('a' - 'A'), stderr);
  return rc;
}
#define pread observed_pread
#define write observed_write
#define fsync observed_fsync
#define close observed_close
#include "../portable/store.c"
#undef pread
#undef write
#undef fsync
#undef close

int64_t qosp_load_plugin(const qos_plugin_t *p, char *out, uint64_t cap) {
  (void)p; (void)out; (void)cap; return -1;
}
int64_t qosp_unload_plugin(const qos_unload_t *p, char *out, uint64_t cap) {
  (void)p; (void)out; (void)cap; return -1;
}
int64_t qosp_compile_call(const char *p, uint64_t n, char *out, uint64_t cap) {
  (void)p; (void)n; (void)out; (void)cap; return -1;
}
static int hex_digit(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}
int main(int argc, char **argv) {
  if (argc < 2) return 2;
  qosp_store_bind("probe");
  if (!strcmp(argv[1], "lock")) {
    char out[256];
    int64_t bad = qosp_store_call(4, NULL, 0, out, sizeof out);
    int64_t next = qosp_store_call(3, NULL, 0, out, sizeof out);
    printf("%lld %lld\n", (long long)bad, (long long)next);
    return 0;
  }
  uint64_t tag = strtoull(argv[1], NULL, 10);
  const char *hex = argc > 2 ? argv[2] : "";
  size_t n = strlen(hex) / 2;
  if (strlen(hex) % 2) return 2;
  char *pay = malloc(n ? n : 1);
  if (!pay) return 2;
  for (size_t i = 0; i < n; i++) {
    int a = hex_digit(hex[i * 2]), b = hex_digit(hex[i * 2 + 1]);
    if (a < 0 || b < 0) return 2;
    pay[i] = (char)(a * 16 + b);
  }
  size_t cap = argc > 3 ? (size_t)strtoull(argv[3], NULL, 10) : 4096;
  if (cap > 1024 * 1024) return 2;
  char *out = cap ? calloc(1, cap) : NULL;
  if (cap && !out) return 2;
  uint64_t len = n;
  if (getenv("QOS_STORE_TEST_INVALID_LENGTH")) { len = UINT64_MAX; free(pay); pay = NULL; }
  int64_t rc = qosp_store_call(tag, pay, len, out, cap);
  printf("%lld ", (long long)rc);
  if (rc >= 0) for (int64_t i = 0; i < rc; i++) printf("%02x", (unsigned char)out[i]);
  else if (out) printf("%s", out);
  fputc('\n', stdout);
  free(out); free(pay);
  return 0;
}
