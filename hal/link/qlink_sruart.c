/* qlink_sruart.c -- qlink over Simple-Risc's UART: the serial backend, the
 * board's one port (qlink_board_port, which hal/drivers/qlink_dev.c's
 * instances name) and the qcon_* console the boot HAL prints through. */
#include "qlink_sruart.h"
#include "qlink_port.h"

#define UART ((volatile uint32_t *)0x10000000u)
qport_t qlink_board_port;
static uint32_t (*clock_ms)(void);

static int sr_rx(void *ctx) { (void)ctx; return (UART[1] & 2) ? (int)(UART[2] & 255) : -1; }
static int sr_tx_ready(void *ctx) { (void)ctx; return (int)(UART[1] & 1); }
static void sr_tx(void *ctx, uint8_t b) { (void)ctx; UART[0] = b; }
/* CTRL (+0xc) bit 0: interrupt (PLIC source 10) while received bytes wait */
static void sr_arm(void *ctx, int rx) { (void)ctx; UART[3] = rx ? 1u : 0u; }
static uint32_t sr_now(void *ctx) { (void)ctx; return clock_ms(); }

void qcon_init(uint32_t (*now_ms)(void)) {
  clock_ms = now_ms;
  qport_serial io = {sr_rx, sr_tx_ready, sr_tx, sr_arm, sr_now, 0};
  qport_init(&qlink_board_port, &io);
}

void qcon_poll(void) { qport_poll(&qlink_board_port); }
void qcon_flush(void) { qport_con_flush(&qlink_board_port); }

void qcon_putc(char c) {
  qport_t *p = &qlink_board_port;
  if (!p->ready) { while (!(UART[1] & 1)) {} UART[0] = (uint8_t)c; return; }
  uint8_t b = (uint8_t)c;
  while (!qport_con_write(p, &b, 1)) qport_poll(p);
  if (c == '\n') qport_con_flush(p);
}

int qcon_getc(void) {
  uint8_t b;
  return qport_con_read(&qlink_board_port, &b, 1) ? b : -1;
}

int qcon_drain(uint32_t ms) { return qport_drain(&qlink_board_port, ms); }
