#include "devtable.h"
#include "fpr.h"
#include "sd.h"
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

#define BASE 131072u
#define PAGES 64
static sd_card_t card;
static unsigned char page[4096];
static int ready;
static void setup(void) {
  if (ready)
    return;
  sd_use_dma(0);
  if (sd_init(&card, 15) || card.blocks < BASE + 8 * PAGES)
    fpr_cpanic("sd init");
  if (mode == 'W') {
    for (unsigned i = 0; i < 8 * PAGES; i++)
      if (sd_write(&card, BASE + i, page))
        fpr_cpanic("format");
  }
  ready = 1;
}
static const devtable_entry_t tab[] = {{"blk", {T_DEVICE, 0, 0}, setup}};
const devtable_entry_t *hal_devtable_ext(uw *n) {
  *n = 1;
  return tab;
}
static V cap(V d) {
  (void)d;
  return TAG(PAGES);
}
static unsigned addr(V p) {
  if (!ISINT(p) || UNTAG(p) < 0 || UNTAG(p) >= PAGES)
    fpr_cpanic("bad page");
  return BASE + 8 * UNTAG(p);
}
static V rd(V d, V p) {
  (void)d;
  unsigned l = addr(p);
  for (int i = 0; i < 8; i++)
    if (sd_read(&card, l + i, page + 512 * i))
      fpr_cpanic("sd read");
  return (V)fpr_mkstr(page, 4096);
}
static V wr(V d, V p, V s) {
  (void)d;
  if (mode != 'W')
    fpr_cpanic("read-only boot");
  unsigned l = addr(p);
  str_t *v = (str_t *)s;
  if (v->len > 4096)
    fpr_cpanic("size");
  for (int i = 0; i < 4096; i++)
    page[i] = i < v->len ? v->bytes[i] : 0;
  for (int i = 0; i < 8; i++)
    if (sd_write(&card, l + i, page + 512 * i))
      fpr_cpanic("sd write");
  return TAG(v->len);
}
static V flush(V u) { return TAG(1); }
FPR_FN(fpr_g_blkPages, cap, 1);
FPR_FN(fpr_g_blkRead, rd, 2);
FPR_FN(fpr_g_blkWrite, wr, 3);
FPR_FN(fpr_g_blkFlush, flush, 1);
static V range(V d, V p, V n) {
  int k = UNTAG(n);
  if (k < 1 || k > 8 || UNTAG(p) > PAGES - k)
    fpr_cpanic("range");
  str_t *v = (str_t *)fpr_alloc(sizeof(*v) + 4096 * k);
  v->tid = T_STR;
  v->var = 0;
  v->len = 4096 * k;
  unsigned l = addr(p);
  for (int i = 0; i < 8 * k; i++)
    if (sd_read(&card, l + i, (uint8_t *)v->bytes + 512 * i))
      fpr_cpanic("range read");
  return (V)v;
}
static V record(V d, V p, V h, V s) {
  str_t *v = (str_t *)s;
  unsigned k = (v->len + 4095) / 4096;
  if (k > 7 || UNTAG(p) >= PAGES - k)
    fpr_cpanic("record");
  wr(d, p, h);
  for (unsigned i = 0; i < k; i++) {
    unsigned n = v->len - 4096 * i;
    if (n > 4096)
      n = 4096;
    wr(d, TAG(UNTAG(p) + 1 + i),
       (V)fpr_mkstr((uint8_t *)v->bytes + 4096 * i, n));
  }
  return TAG(((str_t *)h)->len + v->len);
}
FPR_FN(fpr_g_blkReadRange, range, 3);
FPR_FN(fpr_g_blkWriteRecord, record, 4);
V fpr_g_blkPackPair_call3(V a, V b, V c) {
  fpr_cpanic("pair outside probe");
  return 0;
}
V fpr_g_blkWaitInbox_call2(V a, V b) {
  fpr_cpanic("async outside probe");
  return 0;
}
