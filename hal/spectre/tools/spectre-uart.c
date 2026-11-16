/* spectre-uart: the serial side of the Spectre board checks.
 *
 *   spectre-uart PORT OP...
 *
 * The operations run in order on one open port (8N1, 54 MHz / 868 baud):
 *
 *   send-line TEXT        TEXT and a newline, one byte every 6 ms (the prompt has no flow control)
 *   send-hex HEX          raw bytes
 *   expect TEXT SECONDS   read until what has arrived since the last expect holds TEXT
 *   expect-count TEXT N SECONDS    ... holds TEXT N times and ends with a newline
 *   delay MS
 *   wait-gone SECONDS / wait-present SECONDS    wait for the port's device node to go or come
 *
 * Everything received is written to standard output as it arrives. An expect
 * that times out ends the program with status 3 (what arrived is still
 * printed). The port opens at the first operation that needs it, so a
 * wait-gone / wait-present pair can come first. This is the transport the
 * Python checks took from Simple-Risc's run_program.open_port and
 * rom_protocol.FdTransport; the Sol checks hold the logic.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#define BAUD 62212 /* round(54e6 / 868) */

static void die(const char *why) { fprintf(stderr, "spectre-uart: %s\n", why); exit(1); }
static double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
static void pause_ms(double ms) {
  struct timespec t = {(time_t)(ms / 1000.0), (long)((ms - 1000.0 * (double)(long)(ms / 1000.0)) * 1e6)};
  nanosleep(&t, 0);
}

static int open_port(const char *path) {
  int fd = open(path, O_RDWR | O_NOCTTY | O_NONBLOCK);
  if (fd < 0) { fprintf(stderr, "spectre-uart: cannot open %s: %s\n", path, strerror(errno)); exit(1); }
  struct termios t;
  if (tcgetattr(fd, &t)) die("tcgetattr failed");
  t.c_iflag = t.c_oflag = t.c_lflag = 0;
  t.c_cflag = CS8 | CREAD | CLOCAL;
  cfsetispeed(&t, B115200); cfsetospeed(&t, B115200);
  if (tcsetattr(fd, TCSANOW, &t)) die("tcsetattr failed");
#ifdef __APPLE__
  speed_t speed = BAUD;
  if (ioctl(fd, _IOW('T', 2, speed_t), &speed)) die("cannot set the baud rate (IOSSIOSPEED)");
#else
  die("the custom baud rate is implemented for macOS only");
#endif
  tcflush(fd, TCIOFLUSH);
  return fd;
}

static void write_all(int fd, const unsigned char *p, size_t n) {
  double deadline = now() + 5.0;
  while (n) {
    ssize_t w = write(fd, p, n);
    if (w > 0) { p += w; n -= (size_t)w; continue; }
    if (w < 0 && errno != EAGAIN && errno != EINTR) die("write failed");
    if (now() > deadline) die("write timed out");
    fd_set ws; FD_ZERO(&ws); FD_SET(fd, &ws);
    struct timeval tv = {0, 100000};
    select(fd + 1, 0, &ws, 0, &tv);
  }
}

static size_t count(const char *hay, size_t n, const char *needle) {
  size_t m = strlen(needle), k = 0;
  if (!m || !hay || n < m) return 0;
  for (size_t i = 0; i + m <= n; i++)
    if (!memcmp(hay + i, needle, m)) { k++; i += m - 1; }
  return k;
}

/* What has arrived and no expect has consumed yet. An expect consumes through
 * the end of its match and leaves the rest for the next one, so bytes that
 * arrive in the same read as a prompt are not lost to the wait that follows. */
static char *pend;
static size_t pend_n, pend_cap;

/* read until `needle` has arrived `times` times (and, if `line`, the data ends in a newline) */
static void expect(int fd, const char *needle, size_t times, int line, double seconds) {
  size_t m = strlen(needle);
  double deadline = now() + seconds;
  for (;;) {
    if (count(pend, pend_n, needle) >= times && (!line || (pend_n && pend[pend_n - 1] == '\n'))) {
      size_t used = pend_n;
      if (!line && times == 1 && m) { /* through the end of the first match */
        for (size_t i = 0; i + m <= pend_n; i++)
          if (!memcmp(pend + i, needle, m)) { used = i + m; break; }
      }
      memmove(pend, pend + used, pend_n - used);
      pend_n -= used;
      return;
    }
    double left = deadline - now();
    if (left <= 0) { fflush(stdout); fprintf(stderr, "spectre-uart: timed out waiting for \"%s\"\n", needle); exit(3); }
    fd_set rs; FD_ZERO(&rs); FD_SET(fd, &rs);
    struct timeval tv = {(time_t)left, (suseconds_t)((left - (double)(time_t)left) * 1e6)};
    if (select(fd + 1, &rs, 0, 0, &tv) <= 0) continue;
    if (pend_n + 4096 > pend_cap && !(pend = realloc(pend, pend_cap = (pend_cap ? pend_cap * 2 : 1 << 16)))) die("out of memory");
    ssize_t r = read(fd, pend + pend_n, pend_cap - pend_n);
    if (r > 0) { fwrite(pend + pend_n, 1, (size_t)r, stdout); fflush(stdout); pend_n += (size_t)r; }
    else if (r == 0 || (errno != EAGAIN && errno != EINTR)) die("the port closed");
  }
}

static void wait_node(const char *path, int present, double seconds) {
  double deadline = now() + seconds;
  struct stat st;
  while ((stat(path, &st) == 0) != present) {
    if (now() > deadline) die("timed out waiting for the USB transition");
    pause_ms(100);
  }
}

int main(int argc, char **argv) {
  if (argc < 3) die("usage: spectre-uart PORT OP... (see the source for the operations)");
  const char *port = argv[1];
  int fd = -1;
#define NEED(k) if (i + (k) >= argc) die("an operation is missing its arguments")
#define OPEN() if (fd < 0) fd = open_port(port)
  for (int i = 2; i < argc; i++) {
    const char *op = argv[i];
    if (!strcmp(op, "send-line")) {
      NEED(1); OPEN();
      const char *text = argv[++i];
      for (const char *p = text;; p++) {
        unsigned char c = *p ? (unsigned char)*p : '\n';
        write_all(fd, &c, 1);
        pause_ms(6);
        if (!*p) break;
      }
    } else if (!strcmp(op, "send-hex")) {
      NEED(1); OPEN();
      const char *hex = argv[++i];
      size_t n = strlen(hex);
      if (n % 2) die("send-hex takes whole bytes");
      for (size_t k = 0; k < n; k += 2) {
        char pair[3] = {hex[k], hex[k + 1], 0};
        unsigned char c = (unsigned char)strtoul(pair, 0, 16);
        write_all(fd, &c, 1);
      }
    } else if (!strcmp(op, "expect")) {
      NEED(2); OPEN();
      const char *text = argv[++i];
      expect(fd, text, 1, 0, atof(argv[++i]));
    } else if (!strcmp(op, "expect-count")) {
      NEED(3); OPEN();
      const char *text = argv[++i];
      size_t times = (size_t)atol(argv[++i]);
      expect(fd, text, times, 1, atof(argv[++i]));
    } else if (!strcmp(op, "delay")) {
      NEED(1);
      pause_ms(atof(argv[++i]));
    } else if (!strcmp(op, "wait-gone")) {
      NEED(1);
      wait_node(port, 0, atof(argv[++i]));
    } else if (!strcmp(op, "wait-present")) {
      NEED(1);
      wait_node(port, 1, atof(argv[++i]));
    } else die("unknown operation");
  }
  if (fd >= 0) close(fd);
  return 0;
}
