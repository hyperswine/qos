/* qhost: the host side of a QOS Native board's qlink (hal/ql/qlink.h).
 *
 *   qhost attach PORT [--mhz N] [--settle S]
 *       An interactive console: keys go to the board in console frames,
 *       its console frames come back to this terminal (Ctrl-] quits).
 *   qhost script PORT [--mhz N] [--settle S] OP...
 *       send-line TEXT          a line to the board's console
 *       expect TEXT SECONDS     wait until console output since the last
 *                               expect holds TEXT
 *       soak N SECONDS          send `soak N`, then check N numbered lines
 *                               (each carrying 03, 7E and 7D) arrive in order
 *       delay MS
 *
 * Opening sends a control HELLO; the board starts a new session and answers.
 * PORT is a serial device (baud = N MHz * 1e6 / 868, default 84) or
 * unix:/path (QEMU -serial unix:/path,server). Bytes the board sends outside
 * frames (ROM output, panics) are shown as they come.
 *
 * Pacing: one console frame in flight to the board (window 1, at most 14
 * payload bytes), written in pieces of at most 24 bytes 3 ms apart. The
 * Tang Nano's USB bridge drops board-to-host bytes when a single host write
 * is large (docs/2026-11-18-SPECTRE-84-SPIKES.md).
 * Exit: 0 pass, 1 failure, 2 usage, 3 timeout. */
#define _DARWIN_C_SOURCE
#define _GNU_SOURCE
#include "qlink.h"
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#ifdef __APPLE__
#include <IOKit/serial/ioss.h>
#else
#include <asm/termbits.h>
#endif

static void die(int code, const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  fputs("qhost: ", stderr);
  vfprintf(stderr, fmt, ap);
  fputc('\n', stderr);
  va_end(ap);
  exit(code);
}

static double now_s(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}
static uint32_t ms(void *ctx) { (void)ctx; return (uint32_t)(now_s() * 1000); }
static void sleep_ms(double v) {
  struct timespec t = {(time_t)(v / 1000), (long)(fmod(v, 1000.0) * 1e6)};
  nanosleep(&t, 0);
}

static int fd = -1;
static int is_serial;
static double last_write;

/* ---- the port -------------------------------------------------------------- */
static void open_port(const char *port, double mhz, double settle) {
  if (!strncmp(port, "unix:", 5)) {
    struct sockaddr_un a = {.sun_family = AF_UNIX};
    snprintf(a.sun_path, sizeof a.sun_path, "%s", port + 5);
    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0 || connect(fd, (struct sockaddr *)&a, sizeof a)) die(1, "connect %s: %s", port + 5, strerror(errno));
    fcntl(fd, F_SETFL, O_NONBLOCK);
    return;
  }
  is_serial = 1;
  fd = open(port, O_RDWR | O_NOCTTY | O_NONBLOCK);
  if (fd < 0) die(1, "open %s: %s", port, strerror(errno));
  unsigned long baud = (unsigned long)llround(mhz * 1e6 / 868);
#ifdef __APPLE__
  struct termios t;
  if (tcgetattr(fd, &t)) die(1, "tcgetattr: %s", strerror(errno));
  t.c_iflag = t.c_oflag = t.c_lflag = 0;
  t.c_cflag = CS8 | CREAD | CLOCAL;
  cfsetispeed(&t, B115200);
  cfsetospeed(&t, B115200);
  if (tcsetattr(fd, TCSANOW, &t)) die(1, "tcsetattr: %s", strerror(errno));
  speed_t speed = (speed_t)baud;
  if (ioctl(fd, IOSSIOSPEED, &speed)) die(1, "IOSSIOSPEED %lu: %s", baud, strerror(errno));
#else
  struct termios2 t;
  if (ioctl(fd, TCGETS2, &t)) die(1, "TCGETS2: %s", strerror(errno));
  t.c_iflag = t.c_oflag = t.c_lflag = 0;
  t.c_cflag = CS8 | CREAD | CLOCAL | BOTHER;
  t.c_ispeed = t.c_ospeed = (speed_t)baud;
  if (ioctl(fd, TCSETS2, &t)) die(1, "TCSETS2: %s", strerror(errno));
#endif
  tcflush(fd, TCIOFLUSH);
  if (settle > 0) { sleep_ms(settle * 1000); tcflush(fd, TCIFLUSH); }
}

static void write_all(const uint8_t *b, size_t n) {
  while (n) {
    fd_set w;
    FD_ZERO(&w);
    FD_SET(fd, &w);
    struct timeval tv = {5, 0};
    if (select(fd + 1, 0, &w, 0, &tv) <= 0) die(1, "write timeout");
    ssize_t k = write(fd, b, n);
    if (k < 0) { if (errno == EAGAIN || errno == EINTR) continue; die(1, "write: %s", strerror(errno)); }
    b += k;
    n -= (size_t)k;
  }
  if (is_serial) tcdrain(fd);
}

/* qlink's wire writer: pieces of at most 24 bytes, 3 ms apart */
static void wire(void *ctx, const uint8_t *b, size_t n) {
  (void)ctx;
  while (n) {
    size_t k = n > 24 ? 24 : n;
    double gap = 3.0 - (now_s() - last_write) * 1000;
    if (gap > 0) sleep_ms(gap);
    write_all(b, k);
    last_write = now_s();
    b += k;
    n -= k;
  }
}

/* ---- what the board sends ---------------------------------------------------- */
static int echo_out = 1;
static char *seen;           /* console output since the last expect */
static size_t seen_n, seen_cap;
static void seen_add(const uint8_t *p, size_t n) {
  if (seen_n + n + 1 > seen_cap) {
    seen_cap = (seen_n + n + 1) * 2;
    seen = realloc(seen, seen_cap);
    if (!seen) die(1, "out of memory");
  }
  memcpy(seen + seen_n, p, n);
  seen_n += n;
  seen[seen_n] = 0;
}
static int hello_seen;
static uint8_t nonce; /* this session's HELLO nonce, never 0 */
static void deliver(void *ctx, uint8_t ch, const uint8_t *p, size_t n) {
  (void)ctx;
  if (ch == QLINK_CH_CONTROL && n == 6 && !memcmp(p, "HELLO", 5)) { if (p[5] == nonce) hello_seen = 1; return; }
  if (!hello_seen) return; /* the board's previous session, before it answered */
  if (ch != QLINK_CH_CONSOLE) return;
  if (echo_out) { fwrite(p, 1, n, stdout); fflush(stdout); }
  seen_add(p, n);
}
static void raw(void *ctx, uint8_t b) {
  (void)ctx;
  if (echo_out) { fputc(b, stdout); fflush(stdout); }
  seen_add(&b, 1);
}

static qlink_t ql;

static void pump(double seconds) {
  fd_set r;
  FD_ZERO(&r);
  FD_SET(fd, &r);
  struct timeval tv = {(time_t)seconds, (suseconds_t)(fmod(seconds, 1.0) * 1e6)};
  if (select(fd + 1, &r, 0, 0, &tv) > 0) {
    uint8_t buf[4096];
    ssize_t k = read(fd, buf, sizeof buf);
    if (k > 0) qlink_input(&ql, buf, (size_t)k);
    /* Before the board answers HELLO its frames belong to an old session:
     * acknowledging them only adds bytes to its receive FIFO. */
    if (!hello_seen) ql.ack_owed = 0;
    else if (k == 0) die(1, "the port closed");
  }
  qlink_poll(&ql);
}

/* send console bytes, one small frame in flight */
static void send_console(const uint8_t *p, size_t n, double deadline) {
  while (n) {
    while (!qlink_can_send(&ql)) { if (now_s() > deadline) die(3, "timeout sending to the board"); pump(0.005); }
    size_t k = n > ql.cfg.payload_max ? ql.cfg.payload_max : n;
    qlink_send(&ql, QLINK_CH_CONSOLE, p, k);
    p += k;
    n -= k;
  }
  while (!qlink_idle(&ql)) { if (now_s() > deadline) die(3, "timeout: the board did not acknowledge"); pump(0.005); }
}

static int expect(const char *text, double seconds) {
  double end = now_s() + seconds;
  while (!seen || !strstr(seen, text)) {
    if (now_s() > end) { fprintf(stderr, "qhost: timed out waiting for \"%s\"\n", text); return 0; }
    pump(0.02);
  }
  seen_n = 0;
  seen[0] = 0;
  return 1;
}

static int soak(long count, double seconds) {
  char cmd[64];
  int len = snprintf(cmd, sizeof cmd, "soak %ld\n", count);
  seen_n = 0;
  if (seen) seen[0] = 0;
  double t0 = now_s();
  send_console((uint8_t *)cmd, (size_t)len, t0 + 10);
  double end = t0 + seconds;
  long next = 0;
  size_t pos = 0, bytes = 0;
  const char *tail = " 0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  for (;;) {
    char *nl;
    while (seen && (nl = memchr(seen + pos, '\n', seen_n - pos))) {
      size_t ln = (size_t)(nl - (seen + pos));
      char want[160];
      int wn = snprintf(want, sizeof want, "S%ld \x03\x7e\x7d%s", next, tail);
      if (ln == (size_t)wn && !memcmp(seen + pos, want, ln)) { next++; bytes += ln + 1; }
      else if (next == count && ln >= 9 && !memcmp(seen + pos, "soak done", 9)) {
        double dt = now_s() - t0;
        printf("soak: %ld lines, %zu bytes in %.1f s (%.0f B/s); frames in %u, resent by host %u, crc errors %u, duplicates %u\n",
               count, bytes, dt, bytes / dt, ql.stats.frames_in, ql.stats.resent, ql.stats.crc_errors, ql.stats.dup_frames);
        return 1;
      } else if (next > 0 || (ln && seen[pos] == 'S')) {
        fprintf(stderr, "qhost: soak line %ld wrong: \"%.*s\"\n", next, (int)(ln > 120 ? 120 : ln), seen + pos);
        return 0;
      }
      pos += ln + 1;
    }
    if (now_s() > end) { fprintf(stderr, "qhost: soak timed out at line %ld of %ld\n", next, count); return 0; }
    pump(0.02);
  }
}

/* Tell the board this session is over and wait until it stops sending
 * before the port closes: closing and reopening the Tang Nano's UART while
 * the FPGA transmits wedges its BL616 bridge until a replug (simple-risc
 * boards/tangnano20k/README.md, "Known issue"). */
static void bye(void) {
  if (!hello_seen) return;
  for (int i = 0; i < 3; i++) qlink_send_unreliable(&ql, QLINK_CH_CONTROL, (const uint8_t *)"BYE", 3);
  double end = now_s() + 2.0, quiet_since = now_s();
  while (now_s() < end && now_s() - quiet_since < 0.15) {
    fd_set r;
    FD_ZERO(&r);
    FD_SET(fd, &r);
    struct timeval tv = {0, 20000};
    if (select(fd + 1, &r, 0, 0, &tv) > 0) {
      uint8_t buf[512];
      if (read(fd, buf, sizeof buf) > 0) quiet_since = now_s();
    }
  }
}
static void on_signal(int sig) { (void)sig; exit(130); }

static struct termios saved_tty;
static void restore_tty(void) { tcsetattr(0, TCSANOW, &saved_tty); }

static int attach(void) {
  int tty = isatty(0);
  if (tty) {
    tcgetattr(0, &saved_tty);
    struct termios t = saved_tty;
    cfmakeraw(&t);
    tcsetattr(0, TCSANOW, &t);
    atexit(restore_tty);
    fprintf(stderr, "qhost: attached (Ctrl-] quits)\r\n");
  }
  for (;;) {
    fd_set r;
    FD_ZERO(&r);
    FD_SET(fd, &r);
    FD_SET(0, &r);
    struct timeval tv = {0, 20000};
    if (select(fd + 1, &r, 0, 0, &tv) > 0) {
      if (FD_ISSET(fd, &r)) {
        uint8_t buf[4096];
        ssize_t k = read(fd, buf, sizeof buf);
        if (k > 0) qlink_input(&ql, buf, (size_t)k);
    /* Before the board answers HELLO its frames belong to an old session:
     * acknowledging them only adds bytes to its receive FIFO. */
    if (!hello_seen) ql.ack_owed = 0;
        else if (k == 0) return 1;
      }
      if (FD_ISSET(0, &r)) {
        uint8_t keys[64];
        ssize_t k = read(0, keys, sizeof keys);
        if (k <= 0) return 0;
        for (ssize_t i = 0; i < k; i++) if (keys[i] == 0x1d) return 0; /* Ctrl-] */
        send_console(keys, (size_t)k, now_s() + 10);
      }
    }
    qlink_poll(&ql);
  }
}

int main(int argc, char **argv) {
  if (argc < 3 || (strcmp(argv[1], "attach") && strcmp(argv[1], "script")))
    die(2, "usage: qhost attach PORT [--mhz N] [--settle S] | qhost script PORT [--mhz N] [--settle S] OP...");
  const char *mode = argv[1], *port = argv[2];
  double mhz = 84, settle = 0;
  int i = 3;
  for (; i + 1 < argc; i += 2) {
    if (!strcmp(argv[i], "--mhz")) mhz = atof(argv[i + 1]);
    else if (!strcmp(argv[i], "--settle")) settle = atof(argv[i + 1]);
    else break;
  }
  open_port(port, mhz, settle);
  qlink_config_t cfg = {wire, ms, deliver, raw, 0, 1, 14, 300};
  qlink_init(&ql, &cfg);
  /* open a session: the board resets its sequence state and answers HELLO */
  /* every retry repeats the same nonce, so the board resets once */
  nonce = (uint8_t)(1 + (getpid() ^ (unsigned)(now_s() * 1000)) % 255);
  uint8_t hello[6] = {'H', 'E', 'L', 'L', 'O', nonce};
  for (int tries = 0; !hello_seen; tries++) {
    if (tries == 10) die(1, "no qlink HELLO from the board (is it running a qlink console?)");
    qlink_send_unreliable(&ql, QLINK_CH_CONTROL, hello, sizeof hello);
    double end = now_s() + 0.3;
    while (!hello_seen && now_s() < end) pump(0.01);
  }
  qlink_reset(&ql);
  /* end the session on every exit: a board left streaming into a closed
   * port wedged the Tang Nano's USB bridge */
  atexit(bye);
  signal(SIGINT, on_signal);
  signal(SIGTERM, on_signal);
  signal(SIGHUP, on_signal);
  if (!strcmp(mode, "attach")) return attach();
  echo_out = 1;
  for (; i < argc;) {
    const char *op = argv[i];
    if (!strcmp(op, "send-line") && i + 1 < argc) {
      char line[1100];
      int n = snprintf(line, sizeof line, "%s\n", argv[i + 1]);
      seen_n = 0;
      if (seen) seen[0] = 0;
      send_console((uint8_t *)line, (size_t)n, now_s() + 30);
      i += 2;
    } else if (!strcmp(op, "expect") && i + 2 < argc) {
      if (!expect(argv[i + 1], atof(argv[i + 2]))) return 3;
      i += 3;
    } else if (!strcmp(op, "soak") && i + 2 < argc) {
      echo_out = 0;
      if (!soak(atol(argv[i + 1]), atof(argv[i + 2]))) return 1;
      echo_out = 1;
      i += 3;
    } else if (!strcmp(op, "delay") && i + 1 < argc) {
      double end = now_s() + atof(argv[i + 1]) / 1000;
      while (now_s() < end) pump(0.01);
      i += 2;
    } else die(2, "unknown or incomplete op: %s", op);
  }
  return 0;
}
