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
static uint8_t session; /* the current host session nonce, 0 = none */

/* With no host session the board sends no reliable frames and drops console
 * output. Writing into a port nobody reads wedged the Tang Nano's USB bridge
 * twice (board-to-host bytes stopped until a replug), so a session ends on
 * the host's BYE, or when a host stops acknowledging for PEER_LOST_MS. */
#define PEER_LOST_MS 1500u
static uint32_t heard_at, frames_seen;
static void session_end(void) {
  qlink_reset(&link);
  session = 0;
  out_n = 0;
}

/* Bytes taken off the 32-byte receive FIFO but not yet parsed. A window of
 * resends is about 1 KB, 100 ms at line rate, so the FIFO is drained while
 * waiting to transmit; parsing waits for qcon_poll (qlink_input cannot run
 * inside a send). */
static uint8_t rx[1024];
static unsigned rx_head, rx_tail;
static void rx_pull(void) {
  while (UART[1] & 2) {
    uint8_t b = (uint8_t)UART[2];
    if (rx_head - rx_tail < sizeof rx) rx[rx_head++ % sizeof rx] = b;
  }
}
static void wire(void *ctx, const uint8_t *b, size_t n) {
  (void)ctx;
  for (size_t i = 0; i < n; i++) {
    while (!(UART[1] & 1)) rx_pull();
    UART[0] = b[i];
    rx_pull();
  }
}
static uint32_t now(void *ctx) { (void)ctx; return clock_ms(); }
static void deliver(void *ctx, uint8_t ch, const uint8_t *p, size_t n) {
  (void)ctx;
  if (ch == QLINK_CH_CONTROL && (n == 5 || n == 6) && p[0] == 'H' && p[1] == 'E' && p[2] == 'L' && p[3] == 'L' && p[4] == 'O') {
    /* A host (re)opened the link. It repeats one HELLO nonce until it hears
     * the answer, so only a new nonce starts a new session; a repeat is
     * answered again without resetting the sequence state twice. */
    if (n == 5 || p[5] != session || !session) {
      qlink_reset(&link);
      out_n = 0;
      session = n == 6 && p[5] ? p[5] : 1;
    }
    heard_at = clock_ms();
    uint8_t answer[6] = {'H', 'E', 'L', 'L', 'O', session};
    qlink_send_unreliable(&link, QLINK_CH_CONTROL, answer, n);
    return;
  }
  if (ch == QLINK_CH_CONTROL && n == 3 && p[0] == 'B' && p[1] == 'Y' && p[2] == 'E') { session_end(); return; }
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
  rx_pull();
  while (rx_tail != rx_head) {
    uint8_t b[64];
    size_t n = 0;
    while (rx_tail != rx_head && n < sizeof b) b[n++] = rx[rx_tail++ % sizeof rx];
    qlink_input(&link, b, n);
    rx_pull();
  }
  if (link.stats.frames_in != frames_seen) { frames_seen = link.stats.frames_in; heard_at = clock_ms(); }
  if (session && link.in_flight && clock_ms() - heard_at > PEER_LOST_MS) session_end();
  if (session) qlink_poll(&link);
}

void qcon_flush(void) {
  if (!ready || !out_n) return;
  if (!session) { out_n = 0; return; } /* nobody is listening */
  while (session && !qlink_can_send(&link)) qcon_poll();
  if (!session || !out_n) { out_n = 0; return; } /* the session ended, or a new one began, while waiting */
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
  while (ready && session && !qlink_idle(&link) && clock_ms() - t0 < ms) qcon_poll();
  return ready && qlink_idle(&link);
}
