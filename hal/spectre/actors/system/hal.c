/* hal.c -- System.qa's board hooks on a Spectre board (Simple-Risc on the
 * Tang Nano 20K): boot, the console over qlink, the timebase.
 *
 * Everything else is shared with QEMU virt: fprisc's virt machine layer
 * (built with the hal_mtime / hal_timer_arm / hal_putc / hal_poweroff names
 * remapped, as for the Spectre boot image), QOS's RV32 PLIC driver (the
 * Simple-Risc PLIC and CLINT have virt's layout for hart 0), and the device
 * table generated from bsp/spectre84/board.json: blk (SD over SPI), net (no
 * NIC), and con0, in0, clk0, hf0, aud0 on qlink. Simple-Risc's CLINT counts
 * CPU cycles; the runtime's timebase is 10 MHz, converted here. */
#include "fpr.h"
#include "qlink_sruart.h"

extern uint64_t spectre_raw_ticks(void);
extern void spectre_raw_arm(uw, uint64_t);
#ifndef CORE_MHZ /* the board build passes -DCORE_MHZ */
#define CORE_MHZ 84
#endif
static uint64_t boot_ticks;
static uint32_t uptime_ms(void) { return (uint32_t)((spectre_raw_ticks() - boot_ticks) / (CORE_MHZ * 1000u)); }

void fpr_builtin_main(void) {
  boot_ticks = spectre_raw_ticks();
  qcon_init(uptime_ms);
  fpr_rt_init();
  fpr_hart_main(0);
}

/* the runtime's own lines (boot messages, panics) go out raw, outside
 * qlink frames: qhost shows raw bytes whether or not a session is open, and
 * a panic must not depend on the link (docs/2026-11-18-QLINK.md). Frames are
 * written whole on this one hart, so raw bytes never land inside one. */
void hal_putc(char c) {
  volatile uint32_t *u = (volatile uint32_t *)0x10000000u;
  if (c == '\n') { while (!(u[1] & 1)) {} u[0] = '\r'; }
  while (!(u[1] & 1)) {}
  u[0] = (uint8_t)c;
}

void hal_poweroff(int code) {
  (void)code;
  qcon_drain(2000);
  for (;;)
    ;
}

uint64_t hal_mtime(void) {
  uint64_t n = spectre_raw_ticks() - boot_ticks;
  return n / CORE_MHZ * 10 + (n % CORE_MHZ) * 10 / CORE_MHZ;
}
void hal_timer_arm(uw hart, uint64_t delta) {
  spectre_raw_arm(hart, delta / 10 * CORE_MHZ + ((delta % 10) * CORE_MHZ + 9) / 10);
}
