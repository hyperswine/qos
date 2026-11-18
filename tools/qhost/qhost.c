/* qhost: the host side of a QOS Native board's qlink (hal/ql/qlink.h).
 *
 *   qhost attach PORT [--mhz N] [--settle S]
 *       An interactive console: keys go to the board in console frames,
 *       its console frames come back to this terminal (Ctrl-] quits).
 *   qhost script PORT [--mhz N] [--settle S] [--root DIR] [--wait S] OP...
 *       send-line TEXT          a line to the board's console
 *       send TEXT               bytes to the console (\r \n \t \\ escapes)
 *       key CODE                a key press and release on the input channel
 *                               (an evdev key code)
 *       expect-tone SECONDS     wait for a tone on the audio channel
 *       expect TEXT SECONDS     wait until console output since the last
 *                               expect holds TEXT
 *       soak N SECONDS          send `soak N`, then check N numbered lines
 *                               (each carrying 03, 7E and 7D) arrive in order
 *       delay MS
 *
 * Opening sends a control HELLO (again every 0.3 s, for --wait seconds,
 * default 3); the board starts a new session and answers.
 * The host then serves the board's other channels (hal/link/qlink_port.h):
 * the clock (its epoch milliseconds after HELLO and every minute), host
 * files under --root DIR (no ".." and nothing outside DIR; without --root
 * every file request is refused), and audio (tones are reported on stderr
 * and played with afplay on macOS or aplay elsewhere when present). On exit
 * it sends BYE and waits for the line to go quiet before closing.
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
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
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

/* a file request being reassembled from the files channel:
 * [id][op][plen lo,hi][path][dlen lo,hi][data] */
static uint8_t *req;
static size_t req_n, req_cap;
static int req_ready;
static size_t req_need(void) {
  if (req_n < 4) return 4;
  size_t plen = req[2] | (size_t)req[3] << 8;
  if (req_n < 6 + plen) return 6 + plen;
  return 6 + plen + (req[4 + plen] | (size_t)req[5 + plen] << 8);
}
static void req_bytes(const uint8_t *p, size_t n) {
  for (size_t i = 0; i < n; i++) {
    if (req_ready) { fprintf(stderr, "qhost: a second file request arrived before the first was answered\n"); return; }
    if (req_n + 1 > req_cap) {
      req_cap = req_cap ? req_cap * 2 : 1024;
      req = realloc(req, req_cap);
      if (!req) die(1, "out of memory");
    }
    req[req_n++] = p[i];
    if (req_n >= 4 && req_n == req_need() && (req_n < 6 || req_n >= 6 + (req[2] | (size_t)req[3] << 8))) req_ready = 1;
  }
}

static int tones_heard;
static void play_tone(unsigned freq, unsigned dur_ms);
static int deliver(void *ctx, uint8_t ch, const uint8_t *p, size_t n) {
  (void)ctx;
  if (ch == QLINK_CH_CONTROL && n == 6 && !memcmp(p, "HELLO", 5)) { if (p[5] == nonce) hello_seen = 1; return 0; }
  if (!hello_seen) return 0; /* the board's previous session, before it answered */
  if (ch == QLINK_CH_FILES) { req_bytes(p, n); return 0; }
  if (ch == QLINK_CH_AUDIO) {
    if (n == 5 && p[0] == 1) {
      unsigned f = p[1] | p[2] << 8, d = p[3] | p[4] << 8;
      fprintf(stderr, "qhost: tone %u Hz %u ms\n", f, d);
      tones_heard++;
      play_tone(f, d);
    }
    return 0;
  }
  if (ch != QLINK_CH_CONSOLE) return 0;
  if (echo_out) { fwrite(p, 1, n, stdout); fflush(stdout); }
  seen_add(p, n);
  return 0;
}
static void raw(void *ctx, uint8_t b) {
  (void)ctx;
  if (echo_out) { fputc(b, stdout); fflush(stdout); }
  seen_add(&b, 1);
}

static qlink_t ql;
static int port_closed;
static void service(void);

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
    else if (k == 0) { port_closed = 1; die(1, "the port closed"); }
  }
  qlink_poll(&ql);
  service();
}

/* send a message on a reliable channel, one small frame in flight */
static void send_msg(uint8_t ch, const uint8_t *p, size_t n, double deadline) {
  while (n) {
    while (!qlink_can_send(&ql)) { if (now_s() > deadline) die(3, "timeout sending to the board"); pump(0.005); }
    size_t k = n > ql.cfg.payload_max ? ql.cfg.payload_max : n;
    qlink_send(&ql, ch, p, k);
    p += k;
    n -= k;
  }
  while (!qlink_idle(&ql)) { if (now_s() > deadline) die(3, "timeout: the board did not acknowledge"); pump(0.005); }
}
static void send_console(const uint8_t *p, size_t n, double deadline) { send_msg(QLINK_CH_CONSOLE, p, n, deadline); }

/* ---- the board's other channels ---------------------------------------------- */
static const char *root; /* --root: the directory host files are served from */
static char root_real[PATH_MAX];
static double clock_sent;

static void send_clock(void) {
  struct timeval tv;
  gettimeofday(&tv, 0);
  char digits[24];
  int n = snprintf(digits, sizeof digits, "%lld", (long long)tv.tv_sec * 1000 + tv.tv_usec / 1000);
  clock_sent = now_s();
  send_msg(QLINK_CH_CLOCK, (uint8_t *)digits, (size_t)n, now_s() + 10);
}

/* a path the board named, inside root, or NULL with why */
static char *resolve(const uint8_t *p, size_t n, int must_exist, const char **why) {
  static char out[PATH_MAX];
  char rel[PATH_MAX];
  if (!root) { *why = "qhost serves no files (start it with --root DIR)"; return 0; }
  if (n == 0 || n >= sizeof rel) { *why = "bad path"; return 0; }
  memcpy(rel, p, n);
  rel[n] = 0;
  if (rel[0] == '/' || memchr(rel, 0, n)) { *why = "paths are relative to the served root"; return 0; }
  for (char *c = rel; *c; ) {
    char *e = strchr(c, '/');
    size_t len = e ? (size_t)(e - c) : strlen(c);
    if (len == 2 && c[0] == '.' && c[1] == '.') { *why = "\"..\" is not allowed"; return 0; }
    c += len + (e ? 1 : 0);
    if (!e) break;
  }
  snprintf(out, sizeof out, "%s/%s", root_real, rel);
  /* the file itself (or, for a new file, its directory) must resolve inside root */
  char check[PATH_MAX], real[PATH_MAX];
  snprintf(check, sizeof check, "%s", out);
  if (!must_exist) { char *slash = strrchr(check, '/'); if (slash) *slash = 0; }
  if (!realpath(check, real)) { *why = must_exist ? "no such file" : "no such directory"; return 0; }
  size_t rl = strlen(root_real);
  if (strncmp(real, root_real, rl) || (real[rl] && real[rl] != '/')) { *why = "outside the served root"; return 0; }
  return out;
}

static void file_reply(uint8_t id, int ok, const uint8_t *data, size_t n) {
  uint8_t *m = malloc(4 + n);
  if (!m) die(1, "out of memory");
  m[0] = id; m[1] = ok ? 0 : 1; m[2] = (uint8_t)n; m[3] = (uint8_t)(n >> 8);
  if (n) memcpy(m + 4, data, n);
  send_msg(QLINK_CH_FILES, m, 4 + n, now_s() + 60);
  free(m);
}
static void file_error(uint8_t id, const char *why) { file_reply(id, 0, (const uint8_t *)why, strlen(why)); }

static void serve_file(void) {
  uint8_t id = req[0], op = req[1];
  size_t plen = req[2] | (size_t)req[3] << 8;
  const uint8_t *path = req + 4;
  size_t dlen = req[4 + plen] | (size_t)req[5 + plen] << 8;
  const uint8_t *data = req + 6 + plen;
  const char *why = "";
  if (op == 1 || op == 4) { /* READ, LIST: offset (4) + most bytes (2) */
    if (dlen != 6) { file_error(id, "bad read request"); return; }
    size_t off = data[0] | (size_t)data[1] << 8 | (size_t)data[2] << 16 | (size_t)data[3] << 24;
    size_t want = data[4] | (size_t)data[5] << 8;
    char *full = resolve(path, plen, 1, &why);
    if (!full) { file_error(id, why); return; }
    char *text = 0;
    size_t tn = 0;
    if (op == 1) {
      FILE *f = fopen(full, "rb");
      if (!f) { file_error(id, strerror(errno)); return; }
      text = malloc(want ? want : 1);
      if (fseek(f, (long)off, SEEK_SET) == 0) tn = fread(text, 1, want, f);
      fclose(f);
      file_reply(id, 1, (uint8_t *)text, tn);
    } else {
      DIR *d = opendir(full);
      if (!d) { file_error(id, strerror(errno)); return; }
      size_t cap = 256;
      text = malloc(cap);
      struct dirent *e;
      while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        size_t l = strlen(e->d_name);
        if (tn + l + 1 > cap) { while (tn + l + 1 > cap) cap *= 2; text = realloc(text, cap); }
        memcpy(text + tn, e->d_name, l);
        tn += l;
        text[tn++] = '\n';
      }
      closedir(d);
      size_t from = off < tn ? off : tn, k = tn - from < want ? tn - from : want;
      file_reply(id, 1, (uint8_t *)text + from, k);
    }
    free(text);
  } else if (op == 2 || op == 3) { /* WRITE, APPEND */
    char *full = resolve(path, plen, 0, &why);
    if (!full) { file_error(id, why); return; }
    FILE *f = fopen(full, op == 2 ? "wb" : "ab");
    if (!f) { file_error(id, strerror(errno)); return; }
    size_t w = fwrite(data, 1, dlen, f);
    int bad = fclose(f) != 0 || w != dlen;
    if (bad) file_error(id, "write failed");
    else file_reply(id, 1, 0, 0);
  } else file_error(id, "unknown file operation");
}

static void play_tone(unsigned freq, unsigned dur_ms) {
  const char *player = 0;
#ifdef __APPLE__
  if (access("/usr/bin/afplay", X_OK) == 0) player = "/usr/bin/afplay";
#else
  if (access("/usr/bin/aplay", X_OK) == 0) player = "/usr/bin/aplay";
#endif
  if (!player || !freq || !dur_ms) return;
  char path[] = "/tmp/qhost-tone-XXXXXX";
  int t = mkstemp(path);
  if (t < 0) return;
  unsigned rate = 22050, n = rate * dur_ms / 1000;
  uint8_t h[44] = {'R','I','F','F',0,0,0,0,'W','A','V','E','f','m','t',' ',16,0,0,0,1,0,1,0,
                   0,0,0,0,0,0,0,0,2,0,16,0,'d','a','t','a',0,0,0,0};
  uint32_t data = n * 2, riff = 36 + data, br = rate * 2;
  memcpy(h + 4, &riff, 4); memcpy(h + 24, &rate, 4); memcpy(h + 28, &br, 4); memcpy(h + 40, &data, 4);
  if (write(t, h, 44) != 44) { close(t); unlink(path); return; }
  for (unsigned i = 0; i < n; i++) {
    int16_t v = (int16_t)(8000 * sin(2 * M_PI * freq * i / rate));
    if (write(t, &v, 2) != 2) break;
  }
  close(t);
  pid_t pid = fork();
  if (pid == 0) {
    int null = open("/dev/null", O_WRONLY);
    if (null >= 0) { dup2(null, 1); dup2(null, 2); }
    execl(player, player, path, (char *)0);
    _exit(127);
  }
  if (pid > 0) { int st; waitpid(pid, &st, 0); }
  unlink(path);
}

/* answer what the channels asked for; never nested inside itself */
static void service(void) {
  static int busy;
  if (busy || !hello_seen) return;
  busy = 1;
  if (req_ready) { serve_file(); req_n = 0; req_ready = 0; }
  if (clock_sent > 0 && now_s() - clock_sent > 60) send_clock();
  busy = 0;
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
  if (!hello_seen || port_closed) return;
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
    service();
  }
}

int main(int argc, char **argv) {
  if (argc < 3 || (strcmp(argv[1], "attach") && strcmp(argv[1], "script")))
    die(2, "usage: qhost attach PORT [--mhz N] [--settle S] [--root DIR] | qhost script PORT [--mhz N] [--settle S] [--root DIR] OP...");
  const char *mode = argv[1], *port = argv[2];
  double mhz = 84, settle = 0, wait_hello = 3;
  int i = 3;
  for (; i + 1 < argc; i += 2) {
    if (!strcmp(argv[i], "--mhz")) mhz = atof(argv[i + 1]);
    else if (!strcmp(argv[i], "--settle")) settle = atof(argv[i + 1]);
    else if (!strcmp(argv[i], "--wait")) wait_hello = atof(argv[i + 1]);
    else if (!strcmp(argv[i], "--root")) {
      root = argv[i + 1];
      if (!realpath(root, root_real)) die(1, "--root %s: %s", root, strerror(errno));
    } else break;
  }
  open_port(port, mhz, settle);
  qlink_config_t cfg = {wire, ms, deliver, raw, 0, 1, 14, 300};
  qlink_init(&ql, &cfg);
  /* open a session: the board resets its sequence state and answers HELLO */
  /* every retry repeats the same nonce, so the board resets once */
  nonce = (uint8_t)(1 + (getpid() ^ (unsigned)(now_s() * 1000)) % 255);
  uint8_t hello[6] = {'H', 'E', 'L', 'L', 'O', nonce};
  double give_up = now_s() + wait_hello;
  while (!hello_seen) {
    if (now_s() > give_up) die(1, "no qlink HELLO from the board (is it running a qlink console?)");
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
  signal(SIGPIPE, SIG_IGN); /* a guest that powered off closes the socket */
  send_clock();
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
    } else if (!strcmp(op, "send") && i + 1 < argc) { /* bytes as given, with \r \n \t \\ escapes */
      const char *t = argv[i + 1];
      char buf[1100];
      size_t n = 0;
      for (; *t && n < sizeof buf; t++) {
        if (*t == '\\' && t[1]) {
          t++;
          buf[n++] = *t == 'r' ? '\r' : *t == 'n' ? '\n' : *t == 't' ? '\t' : *t;
        } else buf[n++] = *t;
      }
      seen_n = 0;
      if (seen) seen[0] = 0;
      send_console((uint8_t *)buf, n, now_s() + 30);
      i += 2;
    } else if (!strcmp(op, "key") && i + 1 < argc) {
      unsigned code = (unsigned)atoi(argv[i + 1]);
      uint8_t ev[8] = {1, (uint8_t)code, (uint8_t)(code >> 8), 1, 1, (uint8_t)code, (uint8_t)(code >> 8), 0};
      send_msg(QLINK_CH_INPUT, ev, sizeof ev, now_s() + 10);
      i += 2;
    } else if (!strcmp(op, "expect-tone") && i + 1 < argc) {
      double end = now_s() + atof(argv[i + 1]);
      int before = tones_heard;
      while (tones_heard == before) {
        if (now_s() > end) { fprintf(stderr, "qhost: no tone arrived\n"); return 3; }
        pump(0.02);
      }
      i += 2;
    } else if (!strcmp(op, "delay") && i + 1 < argc) {
      double end = now_s() + atof(argv[i + 1]) / 1000;
      while (now_s() < end) pump(0.01);
      i += 2;
    } else die(2, "unknown or incomplete op: %s", op);
  }
  return 0;
}
