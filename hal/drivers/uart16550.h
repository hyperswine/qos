/* uart16550.h -- a 16550-compatible UART as a CONSOLE instance (console.h).
 * QEMU virt's UART0, and QOS Portable's emulated one through its MMIO table. */
#ifndef QOS_DRIVER_UART16550_H
#define QOS_DRIVER_UART16550_H
#include <stdint.h>
#include "../classes/console.h"

typedef struct uart16550 {
  uintptr_t base;
  /* register access; both NULL means plain MMIO at base (QEMU virt).
   * QOS Portable routes them through its HAL table. */
  uint8_t (*rd)(uintptr_t addr);
  void (*wr)(uintptr_t addr, uint8_t v);
} uart16550_t;

extern const qos_console_ops uart16550_ops;

#endif
