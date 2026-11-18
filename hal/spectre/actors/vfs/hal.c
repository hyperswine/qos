#include "devtable.h"
#include "fpr.h"
#include "sd_spi.h"
static void say(const char *s) {
  while (*s)
    hal_putc(*s++);
}
extern uint64_t spectre_raw_ticks(void);
static uint64_t boot_ticks;
static unsigned mode;
void fpr_builtin_main(void) {
  say("MODE?\n");
#ifdef TEST_QEMU
  mode = 'W';
#else
  volatile unsigned *u = (void *)0x10000000;
  while (!(u[1] & 2))
    ;
  mode = u[2] & 255;
#endif
  if (mode != 'W' && mode != 'R')
    for (;;)
      ;
  boot_ticks = spectre_raw_ticks();
  fpr_rt_init();
  fpr_hart_main(0);
}
void hal_putc(char c) {
#ifdef TEST_QEMU
  volatile unsigned char *q = (void *)0x10000000;
  while (!(q[5] & 32))
    ;
  q[0] = c;
  return;
#endif
  volatile unsigned *u = (void *)0x10000000;
  while (!(u[1] & 1))
    ;
  *u = c;
}
void hal_poweroff(int code) {
  (void)code;
  say("END\nDONE");
  for (;;)
    ;
}

// The scheduler uses a 10 MHz timebase; the board CLINT counts CPU clocks.
extern uint64_t spectre_raw_ticks(void);
extern void spectre_raw_arm(uw, uint64_t);
#ifdef TEST_QEMU
#define CORE_MHZ 10
#elif !defined(CORE_MHZ) /* the board build passes -DCORE_MHZ */
#define CORE_MHZ 54
#endif
uint64_t hal_mtime(void) {
  uint64_t n = spectre_raw_ticks() - boot_ticks;
  return n / CORE_MHZ * 10 + (n % CORE_MHZ) * 10 / CORE_MHZ;
}
void hal_timer_arm(uw hart, uint64_t delta) {
  spectre_raw_arm(hart,
                  delta / 10 * CORE_MHZ + ((delta % 10) * CORE_MHZ + 9) / 10);
}

/* The QLog volume: 64 pages from sector 131072, formatted at setup in mode
 * 'W' and read-only in mode 'R' (hal/drivers/sd_spi.c behind the BLOCK class). */
static sd_spi_t disk = {.lba0 = 131072, .pages = 64};
static void disk_setup(void) {
  disk.format = mode == 'W';
  disk.read_only = mode != 'W';
  sd_spi_setup(&disk);
}
static const devtable_entry_t tab[] = {
    {"blk", {T_DEVICE, 0, 0}, disk_setup, NULL, .cls = FPR_DEV_BLOCK, .ops = &sd_spi_ops, .state = &disk}};
const devtable_entry_t *hal_devtable_ext(uw *n) {
  *n = 1;
  return tab;
}
V fpr_g_blkPackPair_call3(V a, V b, V c) {
  fpr_cpanic("pair outside probe");
  return 0;
}
