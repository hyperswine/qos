/* spectre-image: the byte-level steps of the Spectre Native build.
 *
 *   spectre-image lz4 IN OUT                 one raw LZ4 block (what unpack.S expands)
 *   spectre-image media IN OUT               the SD boot slot: header, payload, sector padding
 *   spectre-image sxa IN OUT [--mailbox]     an app package, as hex text
 *   spectre-image patchrom FS HEX ROM OUT    put ROM into the block RAM of a Gowin .fs bitstream
 *
 * These were mkmedia.py, vfs/pack.py, the tail of apps/build-app.py and
 * patchrom.py. The Sol build scripts call this; it is built by them with
 * `cc ... -llz4` (pkg-config liblz4).
 */
#include <lz4.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void die(const char *why) { fprintf(stderr, "spectre-image: %s\n", why); exit(1); }

static uint8_t *slurp(const char *path, size_t *n) {
  FILE *f = fopen(path, "rb");
  if (!f) { fprintf(stderr, "spectre-image: cannot read %s\n", path); exit(1); }
  fseek(f, 0, SEEK_END);
  long size = ftell(f);
  fseek(f, 0, SEEK_SET);
  uint8_t *b = malloc((size_t)size + 1);
  if (!b || fread(b, 1, (size_t)size, f) != (size_t)size) die("read failed");
  fclose(f);
  b[size] = 0;
  *n = (size_t)size;
  return b;
}
static void spill(const char *path, const void *b, size_t n) {
  FILE *f = fopen(path, "wb");
  if (!f || fwrite(b, 1, n, f) != n || fclose(f)) { fprintf(stderr, "spectre-image: cannot write %s\n", path); exit(1); }
}
static void le32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }

/* zlib's CRC-32 (reflected 0xEDB88320) */
static uint32_t crc32(const uint8_t *d, size_t n) {
  uint32_t c = 0xffffffffu;
  for (size_t i = 0; i < n; i++) {
    c ^= d[i];
    for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1)));
  }
  return ~c;
}

static int cmd_lz4(const char *in, const char *out) {
  size_t n;
  uint8_t *d = slurp(in, &n);
  if (n > ((size_t)1 << 21)) die("invalid input or compression failure");
  int bound = LZ4_compressBound((int)n);
  char *b = malloc((size_t)bound);
  int got = b ? LZ4_compress_default((const char *)d, b, (int)n, bound) : 0;
  if (got <= 0) die("invalid input or compression failure");
  spill(out, b, (size_t)got);
  return 0;
}

static int cmd_media(const char *in, const char *out) {
  size_t n;
  uint8_t *d = slurp(in, &n);
  if (!n || n > 2097152) die("boot slot length");
  size_t pad = (512 - n % 512) % 512, total = 512 + n + pad;
  uint8_t *m = calloc(1, total);
  if (!m) die("out of memory");
  le32(m, 0x31544253u); le32(m + 4, (uint32_t)n); le32(m + 8, crc32(d, n));
  memcpy(m + 512, d, n);
  spill(out, m, total);
  return 0;
}

static int cmd_sxa(const char *in, const char *out, int mailbox) {
  size_t n;
  uint8_t *d = slurp(in, &n);
  if (!n || n > 4096) die("an app image is 1 to 4096 bytes");
  uint8_t head[12];
  memcpy(head, mailbox ? "SXA3" : "SXA2", 4);
  le32(head + 4, (uint32_t)n); le32(head + 8, crc32(d, n));
  char *hex = malloc(2 * (12 + n) + 1);
  if (!hex) die("out of memory");
  size_t o = 0;
  for (size_t i = 0; i < 12; i++) o += (size_t)sprintf(hex + o, "%02x", head[i]);
  for (size_t i = 0; i < n; i++) o += (size_t)sprintf(hex + o, "%02x", d[i]);
  spill(out, hex, o);
  return 0;
}

/* ---- patchrom -----------------------------------------------------------
 * A frame line of the bitstream is 3440 '0'/'1' characters: 3376 data bits and
 * a 64-bit tail whose first two bytes are a CRC-16 (0xA001, seeded by the last
 * 48 bits of the line before). The 2048-byte ROM is 64 columns of 256 bits in
 * the frame matrix. The old ROM's columns are found in the matrix, the new
 * ROM's are written in their place, and every changed line gets a new CRC. */
#define FRAME 3440
#define DATA 3376
static void rom_columns(const uint8_t *data, uint8_t v[64][256]) {
  static const int quarter[4] = {0, 128, 64, 192};
  for (int i = 0; i < 16384; i++) {
    int r = quarter[(i >> 4) & 3] + ((i >> 6) & 63);
    v[(i >> 12) * 16 + i % 16][r] = (uint8_t)(48 + ((data[i / 8] >> (i % 8)) & 1));
  }
}
static void bits_to_bytes(const char *bits, size_t nbits, uint8_t *out) { /* big-endian, nbits % 8 == 0 */
  for (size_t i = 0; i < nbits / 8; i++) {
    uint8_t b = 0;
    for (int k = 0; k < 8; k++) b = (uint8_t)((b << 1) | (bits[i * 8 + (size_t)k] == '1'));
    out[i] = b;
  }
}
static uint16_t crc16(const uint8_t *d, size_t n) {
  uint16_t c = 0;
  for (size_t i = 0; i < n; i++) {
    c ^= d[i];
    for (int k = 0; k < 8; k++) c = (uint16_t)((c >> 1) ^ ((0 - (c & 1)) & 0xa001));
  }
  return c;
}
static uint16_t frame_crc(const char *previous, const char *data) {
  uint8_t buf[6 + DATA / 8];
  bits_to_bytes(previous + strlen(previous) - 48, 48, buf);
  bits_to_bytes(data, DATA, buf + 6);
  return crc16(buf, sizeof buf);
}
static unsigned frames_sum(char **rows, size_t n) {
  unsigned sum = 0;
  uint8_t b[DATA / 8];
  for (size_t i = 0; i < n; i++) {
    bits_to_bytes(rows[i], DATA, b);
    for (size_t k = 0; k < DATA / 16; k++) sum += ((unsigned)b[2 * k] << 8) | b[2 * k + 1];
  }
  return sum & 65535;
}

static int cmd_patchrom(const char *fs, const char *hexpath, const char *rompath, const char *out) {
  size_t n;
  char *src = (char *)slurp(fs, &n);
  /* split into lines (the text ends in a newline; lines keep no terminator) */
  size_t nlines = 0, cap = 1024;
  char **lines = malloc(cap * sizeof *lines);
  for (char *p = src; p < src + n;) {
    char *e = memchr(p, '\n', (size_t)(src + n - p));
    if (!e) e = src + n;
    if (nlines == cap) lines = realloc(lines, (cap *= 2) * sizeof *lines);
    lines[nlines++] = p;
    *e = 0;
    p = e + 1;
  }
  size_t nrows = 0;
  size_t *index = malloc(nlines * sizeof *index);
  char **rows = malloc(nlines * sizeof *rows), **before = malloc(nlines * sizeof *before);
  for (size_t i = 0; i < nlines; i++)
    if (strlen(lines[i]) == FRAME) {
      index[nrows] = i;
      rows[nrows] = malloc(DATA + 1); memcpy(rows[nrows], lines[i], DATA); rows[nrows][DATA] = 0;
      before[nrows] = malloc(DATA + 1); memcpy(before[nrows], rows[nrows], DATA + 1);
      nrows++;
    }
  if (nrows < 256) die("too few frame lines");
  /* the old ROM: whitespace-separated 32-bit hex words, little-endian */
  static uint8_t old_rom[2048], new_rom[2048];
  size_t hn, rn;
  char *hex = (char *)slurp(hexpath, &hn);
  size_t words = 0;
  for (char *t = strtok(hex, " \t\r\n"); t; t = strtok(0, " \t\r\n")) {
    if (words >= 512) die("the ROM hex has more than 512 words");
    le32(old_rom + 4 * words++, (uint32_t)strtoul(t, 0, 16));
  }
  if (words != 512) die("the ROM hex must hold 512 words");
  uint8_t *rom = slurp(rompath, &rn);
  if (rn > 2048) die("the new ROM is larger than 2048 bytes");
  memcpy(new_rom, rom, rn);
  static uint8_t o[64][256], w[64][256];
  rom_columns(old_rom, o); rom_columns(new_rom, w);
  /* where does a ROM column start in the matrix, and is it stored reversed?
   * Vote over every (old column, matrix column, direction): first occurrence. */
  size_t best_start = 0; int best_rev = 0; unsigned best = 0;
  unsigned *votes = calloc(2 * nrows, sizeof *votes);
  uint8_t *col = malloc(nrows), sig[256];
  for (int j = 0; j < 64; j++)
    for (int c = 0; c < DATA; c++) {
      for (size_t r = 0; r < nrows; r++) col[r] = (uint8_t)rows[r][c];
      for (int rev = 0; rev < 2; rev++) {
        for (int k = 0; k < 256; k++) sig[k] = rev ? o[j][255 - k] : o[j][k];
        for (size_t s = 0; s + 256 <= nrows; s++)
          if (!memcmp(col + s, sig, 256)) { votes[2 * s + (size_t)rev]++; break; }
      }
    }
  /* Python's Counter.most_common(1): the highest count; ties go to the key
   * counted first, which the unique match below makes immaterial */
  for (size_t s = 0; s < nrows; s++)
    for (int rev = 0; rev < 2; rev++)
      if (votes[2 * s + (size_t)rev] > best) { best = votes[2 * s + (size_t)rev]; best_start = s; best_rev = rev; }
  if (!best) die("the old ROM is not in this bitstream");
  printf("rom columns start at frame row %zu, %s, %u matches\n", best_start, best_rev ? "reversed" : "forward", best);
  for (int j = 0; j < 64; j++) {
    for (int k = 0; k < 256; k++) sig[k] = best_rev ? o[j][255 - k] : o[j][k];
    int found = -1, count = 0;
    for (int c = 0; c < DATA; c++) {
      int same = 1;
      for (int k = 0; k < 256 && same; k++) same = (uint8_t)before[best_start + (size_t)k][c] == sig[k];
      if (same) { found = c; count++; }
    }
    if (count != 1) { fprintf(stderr, "spectre-image: ROM column %d matches %d bitstream columns\n", j, count); exit(1); }
    for (int k = 0; k < 256; k++) rows[best_start + (size_t)k][found] = (char)(best_rev ? w[j][255 - k] : w[j][k]);
  }
  unsigned sum_old = frames_sum(before, nrows), sum_new = frames_sum(rows, nrows);
  FILE *f = fopen(out, "wb");
  if (!f) die("cannot write the patched bitstream");
  size_t r = 0;
  for (size_t i = 0; i < nlines; i++) {
    if (r < nrows && index[r] == i) {
      if (memcmp(rows[r], before[r], DATA)) {
        if (i == 0) die("a frame line has no line before it");
        uint8_t tail[8];
        bits_to_bytes(lines[i] + FRAME - 64, 64, tail);
        uint16_t was = frame_crc(lines[i - 1], before[r]);
        if (was != (uint16_t)(tail[0] | (tail[1] << 8))) die("a frame's CRC does not match before patching");
        uint16_t now = frame_crc(lines[i - 1], rows[r]);
        tail[0] = (uint8_t)now; tail[1] = (uint8_t)(now >> 8);
        fwrite(rows[r], 1, DATA, f);
        for (int b = 0; b < 8; b++)
          for (int k = 7; k >= 0; k--) fputc('0' + ((tail[b] >> k) & 1), f);
        fputc('\n', f);
      } else fprintf(f, "%s\n", lines[i]);
      r++;
    } else fprintf(f, "%s\n", lines[i]);
  }
  if (fclose(f)) die("cannot write the patched bitstream");
  printf("checksums all frames old/new: 0x%x 0x%x\n", sum_old, sum_new);
  return 0;
}

int main(int argc, char **argv) {
  if (argc == 4 && !strcmp(argv[1], "lz4")) return cmd_lz4(argv[2], argv[3]);
  if (argc == 4 && !strcmp(argv[1], "media")) return cmd_media(argv[2], argv[3]);
  if ((argc == 4 || (argc == 5 && !strcmp(argv[4], "--mailbox"))) && !strcmp(argv[1], "sxa")) return cmd_sxa(argv[2], argv[3], argc == 5);
  if (argc == 6 && !strcmp(argv[1], "patchrom")) return cmd_patchrom(argv[2], argv[3], argv[4], argv[5]);
  die("usage: spectre-image lz4 IN OUT | media IN OUT | sxa IN OUT [--mailbox] | patchrom FS HEX ROM OUT");
  return 1;
}
