/* console.h -- the CONSOLE device class: its contract and its ops.
 *
 * A console is text in and out for a user: a UART on QEMU virt, the console
 * channel of qlink on Spectre boards, a host tty on Portable. UART.qa
 * (programs/mods/uart.fpr) is the one service above it; it keeps its own
 * transmit queue and receive buffer, so the class is only the device edge:
 * take what the device can take now, hand over what it has now, and say when
 * to interrupt. One set of FP-RISC primitives (hal/classes/console.c) serves
 * every driver:
 *
 *   {"con0", {T_DEVICE, 0, base}, setup, NULL,
 *    .cls = FPR_DEV_CONSOLE, .irq = 10, .ops = &my_con_ops, .state = &my_state}
 *
 * FP-RISC surface (core/foreign.fpr), d being `device "uart"` or another
 * console instance:
 *   conOpen d          -> Int     reset the device (line settings, interrupts
 *                                 off); 0
 *   conWrite d s       -> Int     bytes of s the device took now (0 .. |s|)
 *   conRead d          -> String  the bytes it holds now ("" when none)
 *   conArm d rx tx     -> Int     interrupt on received data (rx /= 0) and on
 *                                 room to transmit (tx /= 0); 0
 *   conSize d          -> Int     cols * 65536 + rows, 0 when unknown
 *
 * Contract every driver keeps:
 *   - No op blocks for the medium: write takes what fits, read returns what
 *     is there. Waiting is the caller's, on the instance's interrupt.
 *   - Bytes come out in order and none is dropped once write counted it.
 *   - Received bytes are kept until read; a driver whose buffer overflows
 *     drops the newest bytes and counts them (it never blocks the sender).
 *   - The interrupt (the entry's irq) is level: it stays raised while an
 *     armed condition holds, and arm(st, 0, 0) lowers it.
 *   - Ops are called one at a time per instance, from the owning actor.
 */
#ifndef QOS_CLASS_CONSOLE_H
#define QOS_CLASS_CONSOLE_H
#include <stdint.h>

#define QOS_CONSOLE_OPS_VERSION 1u

typedef struct qos_console_ops {
  uint32_t version; /* QOS_CONSOLE_OPS_VERSION */
  void (*open)(void *st);
  uint32_t (*write)(void *st, const uint8_t *p, uint32_t n);
  uint32_t (*read)(void *st, uint8_t *dst, uint32_t max);
  void (*arm)(void *st, int rx, int tx);
  uint32_t (*size)(void *st); /* cols << 16 | rows, 0 unknown; may be NULL */
} qos_console_ops;

#endif
