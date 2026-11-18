/* block.h -- the BLOCK device class: its contract and its ops.
 *
 * A block device is an array of 4 KiB PAGES read and written whole. Records,
 * logs and files are policy above the class (programs/mods/qlog.fpr). One set
 * of FP-RISC primitives (hal/classes/block.c) serves every driver: it checks
 * arguments, allocates results and calls the instance's ops, so a new driver
 * implements only the ops below and names itself in the device table:
 *
 *   {"blk0", {T_DEVICE, 0, base}, setup, NULL,
 *    .cls = FPR_DEV_BLOCK, .ops = &my_blk_ops, .state = &my_state}
 *
 * FP-RISC surface (core/foreign.fpr), d being `device "blk"` or another
 * block instance:
 *   blkPages d                 -> Int     capacity in pages (0: no disk)
 *   blkRead d p                -> String  the 4096 bytes of page p
 *   blkReadRange d p n         -> String  n consecutive pages, 1 <= n <= range_max
 *   blkWrite d p s             -> Int     s (<= 4096 bytes, zero-padded) to page p;
 *                                         bytes accepted
 *   blkWriteRecord d p h s     -> Int     header h (<= one page) to page p, then
 *                                         payload s from page p+1, zero-padded to
 *                                         whole pages; bytes accepted (|h| + |s|)
 *   blkFlush d                 -> Int     0 durable, 1 unsupported, negative failed
 *
 * Contract every driver keeps:
 *   - Pages are BLOCK_PAGE bytes. A read returns exactly what the last
 *     completed write of that page held (or what the medium held before).
 *   - The generic layer has checked page bounds, counts and sizes before any
 *     op runs; an op may assume page + count <= pages().
 *   - Ops are called one at a time per instance (the generic layer does not
 *     serialize; a driver shared by actors on several harts locks inside).
 *   - Failure of the medium (I/O error, deadline, missing disk) FAIL-STOPS
 *     the calling actor with fpr_actor_fail; ops do not return error codes,
 *     except flush (unsupported is not a failure).
 *   - write_record writes the header page and ceil(plen / BLOCK_PAGE)
 *     payload pages in one ordered request; unused bytes are zero.
 */
#ifndef QOS_CLASS_BLOCK_H
#define QOS_CLASS_BLOCK_H
#include <stdint.h>

#define BLOCK_PAGE 4096u
#define QOS_BLOCK_OPS_VERSION 1u

typedef struct qos_block_ops {
  uint32_t version;   /* QOS_BLOCK_OPS_VERSION */
  uint32_t range_max; /* most pages one read_range or write_record may cover */
  uint64_t (*pages)(void *st);
  void (*read)(void *st, uint64_t page, uint32_t count, uint8_t *dst);
  void (*write_record)(void *st, uint64_t page, const uint8_t *hdr, uint32_t hlen,
                       const uint8_t *payload, uint32_t plen);
  int (*flush)(void *st);
} qos_block_ops;

#endif
