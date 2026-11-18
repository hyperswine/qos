/* qlink_test.c -- the qlink session over a simulated wire that drops and
 * corrupts bytes: every reliable message arrives once, in order, both ways,
 * and no frame ever carries a raw 0x03.
 *   cc -O2 -I../../hal/link qlink_test.c ../../hal/link/qlink.c -o qlink_test && ./qlink_test */
#include "qlink.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct side side_t;
struct side {
  qlink_t q; side_t *peer;
  uint8_t wire[1 << 20]; size_t wlen;     /* bytes in flight to the peer */
  uint32_t got; uint32_t expect_next; int bad;
  size_t raw03;
};
static uint32_t clock_ms;
static unsigned loss_ppm, corrupt_ppm;
static uint32_t rng = 1;
static uint32_t rnd(void) { rng = rng * 1103515245u + 12345u; return rng >> 8; }
static uint32_t now(void *ctx) { (void)ctx; return clock_ms; }
static void wr(void *ctx, const uint8_t *b, size_t n) {
  side_t *s = ctx;
  for (size_t i = 0; i < n; i++) {
    if (b[i] == 0x03) s->raw03++;
    if (rnd() % 1000000 < loss_ppm) continue;
    uint8_t v = b[i];
    if (rnd() % 1000000 < corrupt_ppm) v ^= (uint8_t)(1u << (rnd() % 8));
    s->wire[s->wlen++] = v;
  }
}
static void deliver(void *ctx, uint8_t ch, const uint8_t *p, size_t n) {
  side_t *s = ctx;
  if (ch != QLINK_CH_CONSOLE || n != 4) { s->bad++; return; }
  uint32_t v = (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
  if (v != s->expect_next) s->bad++;
  s->expect_next = v + 1; s->got++;
}
static void deliver_wire(side_t *from) {
  /* the peer reads what `from` wrote, in pieces */
  size_t k = from->wlen > 64 ? 64 : from->wlen;
  qlink_input(&from->peer->q, from->wire, k);
  memmove(from->wire, from->wire + k, from->wlen - k); from->wlen -= k;
}
static int run(unsigned loss, unsigned corrupt, uint32_t count, uint8_t wa, uint8_t wb) {
  static side_t a, b;
  memset(&a, 0, sizeof a); memset(&b, 0, sizeof b);
  a.peer = &b; b.peer = &a; loss_ppm = loss; corrupt_ppm = corrupt; clock_ms = 0;
  qlink_config_t ca = {wr, now, deliver, 0, &a, wa, 255, 50}, cb = {wr, now, deliver, 0, &b, wb, 14, 50};
  qlink_init(&a.q, &ca); qlink_init(&b.q, &cb);
  uint32_t sa = 0, sb = 0;
  for (uint32_t step = 0; step < 50000000 && (a.got < count || b.got < count || !qlink_idle(&a.q) || !qlink_idle(&b.q)); step++) {
    uint8_t m[4];
    if (sa < count && qlink_can_send(&a.q)) { m[0]=sa; m[1]=sa>>8; m[2]=sa>>16; m[3]=0x03; if (!qlink_send(&a.q, QLINK_CH_CONSOLE, (uint8_t[]){sa, sa>>8, sa>>16, sa>>24}, 4)) sa++; }
    if (sb < count && qlink_can_send(&b.q)) { if (!qlink_send(&b.q, QLINK_CH_CONSOLE, (uint8_t[]){sb, sb>>8, sb>>16, sb>>24}, 4)) sb++; }
    if (a.wlen) deliver_wire(&a);
    if (b.wlen) deliver_wire(&b);
    qlink_poll(&a.q); qlink_poll(&b.q);
    clock_ms++;
  }
  int ok = a.got == count && b.got == count && !a.bad && !b.bad;
  printf("loss %5u ppm corrupt %5u ppm windows %u/%u: a got %u b got %u, bad %d/%d, resent %u/%u, crc errors %u/%u, raw 0x03 on wire %zu/%zu, %u ms: %s\n",
         loss, corrupt, wa, wb, b.got, a.got, a.bad, b.bad, a.q.stats.resent, b.q.stats.resent,
         a.q.stats.crc_errors, b.q.stats.crc_errors, a.raw03, b.raw03, clock_ms, ok && !a.raw03 && !b.raw03 ? "PASS" : "FAIL");
  return ok && !a.raw03 && !b.raw03;
}
int main(void) {
  int ok = 1;
  ok &= run(0, 0, 20000, 4, 1);
  ok &= run(2000, 0, 5000, 4, 1);
  ok &= run(0, 2000, 5000, 4, 1);
  ok &= run(5000, 5000, 3000, 4, 1);
  ok &= run(20000, 10000, 1000, 2, 1);
  puts(ok ? "qlink: PASS" : "qlink: FAIL");
  return ok ? 0 : 1;
}
