/* qlink_uart16550.c -- qlink over a 16550 UART (QEMU virt's UART0 at
 * 0x10000000): the serial backend and the board's one port. QEMU's
 * `-serial unix:PATH,server` puts tools/qhost on the other end
 * (qhost attach unix:PATH). The port starts on first use (qlink_dev's init). */
#include "qlink_port.h"
#include "fpr.h"

#define U ((volatile uint8_t *)0x10000000u)
qport_t qlink_board_port;

static int u_rx(void *ctx) { (void)ctx; return (U[5] & 1) ? U[0] : -1; }
static int u_tx_ready(void *ctx) { (void)ctx; return (U[5] & 0x20) != 0; }
static void u_tx(void *ctx, uint8_t b) { (void)ctx; U[0] = b; }
static void u_arm(void *ctx, int rx) { (void)ctx; U[1] = rx ? 1 : 0; }
static uint32_t u_now(void *ctx) { (void)ctx; return (uint32_t)(hal_mtime() / 10000); }

void qlink_uart16550_init(void) {
  if (qlink_board_port.ready) return;
  U[3] = 3; /* 8N1; no FCR write (it would drop bytes already received) */
  qport_serial io = {u_rx, u_tx_ready, u_tx, u_arm, u_now, 0};
  qport_init(&qlink_board_port, &io);
}
