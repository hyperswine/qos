/* sd_spi.c -- the SD-over-SPI BLOCK driver (sd_spi.h). One request at a time,
 * polled SPI without DMA; flush is unsupported (sd.c writes through). Medium
 * failures fail-stop the calling actor, as the class contract asks. */
#include "fpr.h"
#include "sd_spi.h"

static uint8_t scratch[BLOCK_PAGE];

void sd_spi_setup(sd_spi_t *s) {
  if (s->ready) return;
  sd_use_dma(0);
  if (sd_init(&s->card, 15) || s->card.blocks < s->lba0 + 8u * s->pages) fpr_cpanic("sd init");
  if (s->format) {
    for (uint32_t i = 0; i < BLOCK_PAGE; i++) scratch[i] = 0;
    for (uint32_t i = 0; i < 8u * s->pages; i++)
      if (sd_write(&s->card, s->lba0 + i, scratch)) fpr_cpanic("sd format");
  }
  s->ready = 1;
}

static uint64_t sd_pages(void *st) {
  sd_spi_t *s = st;
  sd_spi_setup(s);
  return s->pages;
}

static void sd_read_pages(void *st, uint64_t page, uint32_t count, uint8_t *dst) {
  sd_spi_t *s = st;
  uint32_t lba = s->lba0 + 8u * (uint32_t)page;
  for (uint32_t i = 0; i < 8u * count; i++)
    if (sd_read(&s->card, lba + i, dst + 512u * i)) fpr_actor_fail("blk: sd read failed");
}

static void write_page(sd_spi_t *s, uint64_t page, const uint8_t *src, uint32_t len) {
  for (uint32_t i = 0; i < BLOCK_PAGE; i++) scratch[i] = i < len ? src[i] : 0;
  uint32_t lba = s->lba0 + 8u * (uint32_t)page;
  for (uint32_t i = 0; i < 8; i++)
    if (sd_write(&s->card, lba + i, scratch + 512u * i)) fpr_actor_fail("blk: sd write failed");
}

static void sd_write_record(void *st, uint64_t page, const uint8_t *hdr, uint32_t hlen,
                            const uint8_t *payload, uint32_t plen) {
  sd_spi_t *s = st;
  if (s->read_only) fpr_actor_fail("blk: read-only volume");
  write_page(s, page, hdr, hlen);
  for (uint32_t i = 0; i * BLOCK_PAGE < plen; i++) {
    uint32_t n = plen - i * BLOCK_PAGE;
    write_page(s, page + 1 + i, payload + i * BLOCK_PAGE, n > BLOCK_PAGE ? BLOCK_PAGE : n);
  }
}

static int sd_flush(void *st) { (void)st; return 1; }

const qos_block_ops sd_spi_ops = {
  .version = QOS_BLOCK_OPS_VERSION, .range_max = 8,
  .pages = sd_pages, .read = sd_read_pages, .write_record = sd_write_record, .flush = sd_flush,
};

/* blkPackPair (QLog's two-record batch), the same primitive every block
 * board links (hal/blk_pack.h). */
#include "../blk_pack.h"

/* The native block-policy knobs (std/block.fpr: deadline, reset probes,
 * waiter factor) belong to virtio's recovery machinery. An SD card over SPI
 * has none: it reports version 0 with no budget, and refuses any budget as
 * invalid (-1) rather than pretending to apply it. */
static V sd_budget_get(V u) {
  (void)u;
  hdr_t *t = (hdr_t *)fpr_alloc(8 + 4 * sizeof(V));
  t->tid = T_TUP4; t->var = 0;
  V *fields = (V *)((char *)t + 8);
  for (int i = 0; i < 4; i++) fields[i] = TAG(0);
  return (V)t;
}
static V sd_budget_set(V request) { (void)request; return TAG(-1); }
FPR_FN(fpr_g_blkBudgetGet, sd_budget_get, 1);
FPR_FN(fpr_g_blkBudgetSet, sd_budget_set, 1);
