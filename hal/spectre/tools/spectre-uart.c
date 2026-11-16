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
 *   upload IMAGE SECONDS RETRIES   reset to the boot ROM, check its identity (SRID1, 54 MHz,
 *                         capabilities UICG, room for the image), upload with CRC and readback,
 *                         and start the image; needs the original UART ROM in the FPGA
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
#include <stdint.h>
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

static void write_for(int fd, const unsigned char *p, size_t n, double seconds) {
  double deadline = now() + seconds;
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

static void write_all(int fd, const unsigned char *p, size_t n) { write_for(fd, p, n, 5.0); }

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


/* ---- the boot ROM's upload protocol (Simple-Risc rom_protocol: SRID1, SRU1) ---- */
static uint32_t crc32(const unsigned char *d, size_t n) {
  uint32_t c = 0xffffffffu;
  for (size_t i = 0; i < n; i++) {
    c ^= d[i];
    for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1)));
  }
  return ~c;
}
static void le32(unsigned char *p, uint32_t v) { p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8); p[2] = (unsigned char)(v >> 16); p[3] = (unsigned char)(v >> 24); }
/* read for at most `max` seconds, stopping after `quiet` seconds without a byte; with
 * `line`, stop at the first newline instead. Answers the bytes in a static buffer. */
static char rom_buf[4096];
static size_t rom_read(int fd, double quiet, double max, int line) {
  size_t n = 0;
  double start = now(), last = start;
  while (now() - start < max && n + 1 < sizeof rom_buf) {
    if (!line && now() - last >= quiet) break;
    fd_set rs; FD_ZERO(&rs); FD_SET(fd, &rs);
    struct timeval tv = {0, 20000};
    if (select(fd + 1, &rs, 0, 0, &tv) <= 0) continue;
    ssize_t r = read(fd, rom_buf + n, sizeof rom_buf - 1 - n);
    if (r > 0) { n += (size_t)r; last = now(); if (line && memchr(rom_buf, '\n', n)) break; }
  }
  rom_buf[n] = 0;
  return n;
}
/* the last non-empty line of the reply, trimmed, in place */
static char *last_line(char *text) {
  char *best = text + strlen(text);
  for (char *p = strtok(text, "\r\n"); p; p = strtok(0, "\r\n")) {
    while (*p == ' ') p++;
    if (*p) best = p;
  }
  size_t n = strlen(best);
  while (n && best[n - 1] == ' ') best[--n] = 0;
  return best;
}
static const char *field(const char *line, const char *key) {
  const char *p = strstr(line, key);
  return p ? p + strlen(key) : 0;
}
/* reset to the ROM, ask who it is, check it can take this image, upload, read back, start */
static void upload(int fd, const char *path, double timeout, int retries) {
  FILE *f = fopen(path, "rb");
  if (!f) die("cannot read the image");
  fseek(f, 0, SEEK_END);
  long size = ftell(f);
  fseek(f, 0, SEEK_SET);
  if (size <= 0) die("program image must not be empty");
  size_t padded = ((size_t)size + 3) & ~(size_t)3;
  unsigned char *frame = calloc(1, 13 + padded + 4);
  if (!frame || fread(frame + 13, 1, (size_t)size, f) != (size_t)size) die("cannot read the image");
  fclose(f);
  unsigned char c = 3;
  write_all(fd, &c, 1);
  rom_read(fd, 0.12, 0.36, 0);
  int known = 0;
  for (int attempt = 0; attempt < 2 && !known; attempt++) {
    c = 'I';
    write_all(fd, &c, 1);
    rom_read(fd, 0, 0.15, 1);
    if (strstr(rom_buf, "SRID") && strchr(rom_buf, '\n')) known = 1;
    else if (strstr(rom_buf, "ERR")) rom_read(fd, 0.03, 0.15, 0);
    else break;
  }
  if (!known) die("no response from boot ROM on UART (is the UART ROM loaded?)");
  char *id = last_line(rom_buf);
  if (strncmp(id, "SRID1 ", 6)) die("unsupported ROM identity protocol");
  printf("%s\n", id);
  fflush(stdout);
  const char *cpu = field(id, "cpu="), *max = field(id, "max="), *cap = field(id, "cap=");
  if (!cpu || !max || !cap) die("malformed ROM identity reply");
  if (strtoul(cpu, 0, 16) != 54) die("CPU clock mismatch: the board does not report 54 MHz");
  unsigned long limit = strtoul(max, 0, 16);
  if (padded > limit) die("the program image exceeds the board loader's limit");
  for (const char *need = "UICG"; *need; need++) {
    const char *e = cap;
    int found = 0;
    for (; *e && *e != ' '; e++) found |= *e == *need;
    if (!found) die("board loader lacks a required capability (UICG)");
  }
  frame[0] = 'U';
  le32(frame + 1, 0x31555253u); le32(frame + 5, (uint32_t)(padded / 4));
  le32(frame + 9, crc32(frame + 1, 8));
  uint32_t sum = crc32(frame + 13, padded);
  le32(frame + 13 + padded, sum);
  char ok[16], bare[16];
  snprintf(ok, sizeof ok, "OK %08x", sum);
  snprintf(bare, sizeof bare, "%08x", sum);
  const char *why = "no response";
  int done = 0;
  for (int attempt = 0; attempt <= retries && !done; attempt++) {
    if (attempt > 0) { c = 3; write_all(fd, &c, 1); rom_read(fd, 0.12, 0.36, 0); }
    write_for(fd, frame, 13 + padded + 4, (timeout > 5 ? timeout : 5) + (double)padded / 4000.0);
    tcdrain(fd);
    size_t got = rom_read(fd, 0, timeout, 1);
    char *line = last_line(rom_buf);
    if (!strcmp(line, ok)) {
      c = 'C';
      write_all(fd, &c, 1);
      rom_read(fd, 0, timeout, 1);
      if (!strcmp(last_line(rom_buf), bare)) done = 1;
      else why = "readback 'C' CRC mismatch";
    } else if (!strncmp(line, "OK ", 3)) why = "upload CRC mismatch in ROM ack";
    else if (!strncmp(line, "ERR", 3)) why = "ROM rejected upload";
    else why = got ? "unexpected ROM upload reply" : "timed out waiting for ROM upload acknowledgement";
  }
  if (!done) die(why);
  free(frame);
  c = 'G';
  write_all(fd, &c, 1);
  size_t first = rom_read(fd, 0.02, 0.02, 0);
  if (!strncmp(rom_buf, "ERR NOIMG", 9)) die("ROM refused guarded execution ('G'): ERR NOIMG");
  /* what the program said in that window belongs to the next expect */
  if (first) {
    if (pend_n + first > pend_cap && !(pend = realloc(pend, pend_cap = pend_n + first + (1 << 16)))) die("out of memory");
    memcpy(pend + pend_n, rom_buf, first);
    pend_n += first;
    fwrite(rom_buf, 1, first, stdout); fflush(stdout);
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
    } else if (!strcmp(op, "upload")) {
      NEED(3); OPEN();
      const char *image = argv[++i];
      double seconds = atof(argv[++i]);
      upload(fd, image, seconds, atoi(argv[++i]));
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
