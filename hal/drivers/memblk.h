/* memblk.h -- the RAM BLOCK driver (memblk.c), the class's reference. */
#ifndef QOS_MEMBLK_H
#define QOS_MEMBLK_H
#include "../classes/block.h"
typedef struct {
  uint8_t *bytes;     /* pages * BLOCK_PAGE bytes */
  uint64_t pages;
} memblk_t;
extern const qos_block_ops memblk_ops;
#endif
