/* block.c -- the BLOCK class's FP-RISC primitives, once for every driver.
 *
 * Each primitive finds the instance behind its Device (devtable_entry_of),
 * checks the arguments against the contract in block.h, and calls the
 * instance's ops. Failure rules (the virtio driver's, which they replace):
 * a wrong argument TYPE is a programming error (fpr_cpanic); a missing disk,
 * a page out of range or an oversized request fail-stops the calling actor
 * (fpr_actor_fail), as the medium's own failures do inside the ops. */
#include "fpr.h"
#include "devtable.h"
#include "block.h"

static const qos_block_ops *instance(V d, void **st) {
  if (ISINT(d) || !d || TID(d) != T_DEVICE) fpr_cpanic("blk: not a Device");
  const devtable_entry_t *e = devtable_entry_of(d);
  if (e->cls != FPR_DEV_BLOCK || !e->ops) fpr_cpanic("blk: not a block device");
  const qos_block_ops *ops = (const qos_block_ops *)e->ops;
  if (ops->version != QOS_BLOCK_OPS_VERSION) fpr_cpanic("blk: driver built for another block contract");
  *st = e->state;
  return ops;
}

static int is_str(V v) { return !ISINT(v) && v && TID(v) == T_STR; }

static uint64_t capacity(const qos_block_ops *ops, void *st) {
  uint64_t n = ops->pages(st);
  if (!n) fpr_actor_fail("blk: no disk");
  return n;
}

static V h_blkPages(V d) {
  void *st;
  const qos_block_ops *ops = instance(d, &st);
  return TAG((sw)ops->pages(st));
}

static V h_blkRead(V d, V pv) {
  void *st;
  const qos_block_ops *ops = instance(d, &st);
  if (!ISINT(pv)) fpr_cpanic("blkRead: page must be an Int");
  uint64_t pages = capacity(ops, st);
  if (UNTAG(pv) < 0 || (uint64_t)UNTAG(pv) >= pages) fpr_actor_fail("blk: page out of range");
  str_t *s = (str_t *)fpr_alloc(sizeof(str_t) + BLOCK_PAGE);
  s->tid = T_STR; s->var = 0; s->len = BLOCK_PAGE;
  ops->read(st, (uint64_t)UNTAG(pv), 1, (uint8_t *)s->bytes);
  return (V)s;
}

static V h_blkReadRange(V d, V pv, V nv) {
  void *st;
  const qos_block_ops *ops = instance(d, &st);
  if (!ISINT(pv) || !ISINT(nv) || UNTAG(pv) < 0 || UNTAG(nv) < 1 || (uint64_t)UNTAG(nv) > ops->range_max)
    fpr_actor_fail("blk: invalid page range");
  uint64_t pages = capacity(ops, st), page = (uint64_t)UNTAG(pv), count = (uint64_t)UNTAG(nv);
  if (pages < count || page > pages - count) fpr_actor_fail("blk: page out of range");
  str_t *s = (str_t *)fpr_alloc(sizeof(str_t) + count * BLOCK_PAGE);
  s->tid = T_STR; s->var = 0; s->len = count * BLOCK_PAGE;
  ops->read(st, page, (uint32_t)count, (uint8_t *)s->bytes);
  return (V)s;
}

static V h_blkWrite(V d, V pv, V sv) {
  void *st;
  const qos_block_ops *ops = instance(d, &st);
  if (!ISINT(pv)) fpr_cpanic("blkWrite: page must be an Int");
  if (!is_str(sv)) fpr_cpanic("blkWrite: payload must be a String");
  str_t *s = (str_t *)sv;
  if (s->len > BLOCK_PAGE) fpr_cpanic("blkWrite: payload exceeds one page");
  uint64_t pages = capacity(ops, st);
  if (UNTAG(pv) < 0 || (uint64_t)UNTAG(pv) >= pages) fpr_actor_fail("blk: page out of range");
  ops->write_record(st, (uint64_t)UNTAG(pv), (const uint8_t *)s->bytes, (uint32_t)s->len, 0, 0);
  return TAG((sw)s->len);
}

static V h_blkWriteRecord(V d, V pv, V hv, V sv) {
  void *st;
  const qos_block_ops *ops = instance(d, &st);
  if (!ISINT(pv) || UNTAG(pv) < 0 || !is_str(hv) || !is_str(sv)) fpr_actor_fail("blk: invalid record write");
  str_t *header = (str_t *)hv, *payload = (str_t *)sv;
  if (header->len > BLOCK_PAGE || payload->len > (uw)(ops->range_max - 1) * BLOCK_PAGE)
    fpr_actor_fail("blk: record too large");
  uint64_t page = (uint64_t)UNTAG(pv), span = 1 + (payload->len + BLOCK_PAGE - 1) / BLOCK_PAGE;
  uint64_t pages = capacity(ops, st);
  if (pages < span || page > pages - span) fpr_actor_fail("blk: page out of range");
  ops->write_record(st, page, (const uint8_t *)header->bytes, (uint32_t)header->len,
                    (const uint8_t *)payload->bytes, (uint32_t)payload->len);
  return TAG((sw)(header->len + payload->len));
}

static V h_blkFlush(V d) {
  void *st;
  const qos_block_ops *ops = instance(d, &st);
  if (!ops->pages(st) || !ops->flush) return TAG(1);
  return TAG((sw)ops->flush(st));
}

/* Park the calling actor until a message arrives or `until` (microseconds
 * of the 10 MHz timebase) passes: the completion wait block clients use. */
static V h_blkWaitInbox(V me, V until) {
  sw us = UNTAG(until);
  if (us < 0 || (uint64_t)us > UINT64_MAX / 10) return TAG(0);
  return TAG(fpr_wait_any_until_c(me, (uint64_t)us * 10));
}

FPR_FN(fpr_g_blkPages, h_blkPages, 1);
FPR_FN(fpr_g_blkRead, h_blkRead, 2);
FPR_FN(fpr_g_blkReadRange, h_blkReadRange, 3);
FPR_FN(fpr_g_blkWrite, h_blkWrite, 3);
FPR_FN(fpr_g_blkWriteRecord, h_blkWriteRecord, 4);
FPR_FN(fpr_g_blkFlush, h_blkFlush, 1);
FPR_FN(fpr_g_blkWaitInbox, h_blkWaitInbox, 2);
