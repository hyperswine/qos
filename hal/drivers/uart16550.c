/* uart16550.c -- a 16550-compatible UART as a CONSOLE instance.
 *
 * Registers (byte offsets): 0 RBR/THR, 1 IER, 3 LCR, 5 LSR (bit 0 data ready,
 * bit 5 transmit holding register empty). This is the register code that
 * lived in programs/mods/uart.fpr; UART.qa now asks the console class. */
#include "uart16550.h"

static uint8_t rd(const uart16550_t *u, unsigned off) {
  if (u->rd) return u->rd(u->base + off);
  return *(volatile uint8_t *)(u->base + off);
}
static void wr(const uart16550_t *u, unsigned off, uint8_t v) {
  if (u->wr) { u->wr(u->base + off, v); return; }
  *(volatile uint8_t *)(u->base + off) = v;
}

/* 8N1, interrupts off. No FCR write: enabling the FIFO resets the receive
 * FIFO, and System.qa opens the console at boot while the user's first keys
 * may already be buffered (the lost-keystroke bug). QEMU's FIFO is on
 * regardless; a real 16550 bring-up would enable it from reset. */
static void u_open(void *st) {
  uart16550_t *u = st;
  wr(u, 3, 3);
  wr(u, 1, 0);
}

static uint32_t u_write(void *st, const uint8_t *p, uint32_t n) {
  uart16550_t *u = st;
  uint32_t i = 0;
  while (i < n && (rd(u, 5) & 0x20)) wr(u, 0, p[i++]);
  return i;
}

static uint32_t u_read(void *st, uint8_t *dst, uint32_t max) {
  uart16550_t *u = st;
  uint32_t i = 0;
  while (i < max && (rd(u, 5) & 0x01)) dst[i++] = rd(u, 0);
  return i;
}

/* IER: bit 0 received data available, bit 1 transmit holding register empty */
static void u_arm(void *st, int rx, int tx) {
  wr((uart16550_t *)st, 1, (uint8_t)((rx ? 1 : 0) | (tx ? 2 : 0)));
}

const qos_console_ops uart16550_ops = {
    .version = QOS_CONSOLE_OPS_VERSION,
    .open = u_open,
    .write = u_write,
    .read = u_read,
    .arm = u_arm,
    .size = 0,
};
