/* qlink_sruart.c -- see qlink_sruart.h. */
#include "qlink_sruart.h"
#include "qlink.h"

#define UART ((volatile uint32_t *)0x10000000u)
static qlink_t link;
static uint32_t (*clock_ms)(void);
static uint8_t out[200];
static unsigned out_n;
static uint8_t in[512];
static unsigned in_head, in_tail;
static int ready;

static void wire(void *ctx, const uint8_t *b, size_t n) {
  (void)ctx;
  for (size_t i = 0; i < n; i++) {
    while (!(UART[1] & 1)) {}
    UART[0] = b[i];
  }
}
static uint32_t now(void *ctx) { (void)ctx; return clock_ms(); }
static void deliver(void *ctx, uint8_t ch, const uint8_t *p, size_t n) {
  (void)ctx;
  if (ch == QLINK_CH_CONTROL && n == 5 && p[0] == 'H' && p[1] == 'E' && p[2] == 'L' && p[3] == 'L' && p[4] == 'O') {
    qlink_reset(&link); /* a host (re)opened the link: a new session */
    out_n = 0;
    qlink_send_unreliable(&link, QLINK_CH_CONTROL, (const uint8_t *)"HELLO", 5);
    return;
  }
  if (ch != QLINK_CH_CONSOLE) return;
  for (size_t i = 0; i < n; i++)
    if (in_head - in_tail < sizeof in) in[in_head++ % sizeof in] = p[i];
}

void qcon_init(uint32_t (*now_ms)(void)) {
  clock_ms = now_ms;
  qlink_config_t cfg = {wire, now, deliver, 0, 0, 4, 255, 300};
  qlink_init(&link, &cfg);
  ready = 1;
}

void qcon_poll(void) {
  if (!ready) return;
  uint8_t b[32];
  size_t n = 0;
  while ((UART[1] & 2) && n < sizeof b) b[n++] = (uint8_t)UART[2];
  if (n) qlink_input(&link, b, n);
  qlink_poll(&link);
}

void qcon_flush(void) {
  if (!ready || !out_n) return;
  while (!qlink_can_send(&link)) qcon_poll();
  qlink_send(&link, QLINK_CH_CONSOLE, out, out_n);
  out_n = 0;
}

void qcon_putc(char c) {
  if (!ready) { while (!(UART[1] & 1)) {} UART[0] = (uint8_t)c; return; }
  out[out_n++] = (uint8_t)c;
  if (c == '\n' || out_n == sizeof out) qcon_flush();
}

int qcon_getc(void) {
  qcon_poll();
  if (in_tail == in_head) return -1;
  return in[in_tail++ % sizeof in];
}

int qcon_drain(uint32_t ms) {
  qcon_flush();
  uint32_t t0 = clock_ms ? clock_ms() : 0;
  while (ready && !qlink_idle(&link) && clock_ms() - t0 < ms) qcon_poll();
  return ready && qlink_idle(&link);
}
