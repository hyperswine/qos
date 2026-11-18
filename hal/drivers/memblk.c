/* memblk.c -- a BLOCK class driver over RAM: the class's reference driver.
 *
 * It keeps the contract in hal/classes/block.h with nothing else in the way,
 * so a conformance test run against it and against a real driver
 * (tests/blockconform.fpr) shows the real one behaves the same. An image adds
 * an instance with a static memblk_t and one device table line:
 *
 *   static uint8_t ram[16 * BLOCK_PAGE];
 *   static memblk_t mem0 = {.bytes = ram, .pages = 16};
 *   {"mem0", {T_DEVICE, 0, 0}, NULL, NULL, .cls = FPR_DEV_BLOCK,
 *    .ops = &memblk_ops, .state = &mem0}
 */
#include "fpr.h"
#include "memblk.h"

static uint64_t mb_pages(void *st) { return ((memblk_t *)st)->pages; }

static void mb_read(void *st, uint64_t page, uint32_t count, uint8_t *dst) {
  memblk_t *m = st;
  __builtin_memcpy(dst, m->bytes + page * BLOCK_PAGE, (uw)count * BLOCK_PAGE);
}

static void put(memblk_t *m, uint64_t page, const uint8_t *src, uint32_t len) {
  uint8_t *p = m->bytes + page * BLOCK_PAGE;
  __builtin_memcpy(p, src, len);
  __builtin_memset(p + len, 0, BLOCK_PAGE - len);
}

static void mb_write_record(void *st, uint64_t page, const uint8_t *hdr, uint32_t hlen,
                            const uint8_t *payload, uint32_t plen) {
  memblk_t *m = st;
  put(m, page, hdr, hlen);
  for (uint32_t i = 0; i * BLOCK_PAGE < plen; i++) {
    uint32_t n = plen - i * BLOCK_PAGE;
    put(m, page + 1 + i, payload + i * BLOCK_PAGE, n > BLOCK_PAGE ? BLOCK_PAGE : n);
  }
}

static int mb_flush(void *st) { (void)st; return 0; }

const qos_block_ops memblk_ops = {
  .version = QOS_BLOCK_OPS_VERSION, .range_max = 8,
  .pages = mb_pages, .read = mb_read, .write_record = mb_write_record, .flush = mb_flush,
};
