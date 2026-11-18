/* hostfs.h -- the HOSTFS device class: files on a development host.
 *
 *   hfRead d path         -> Result String String   the whole file
 *   hfWrite d path bytes  -> Result String String   replace it; Ok ""
 *   hfAppend d path bytes -> Result String String   append; Ok ""
 *   hfList d path         -> Result String String   entry names, one a line
 *
 * Paths are relative to the root the host serves; the host refuses ".."
 * and anything outside it. Reads and listings come in chunks
 * (offset + HOSTFS_CHUNK) until a short one, so no size is fixed here.
 * Failures are Err values with the reason: refused by the host, no host
 * attached, no answer in time. */
#ifndef QOS_CLASS_HOSTFS_H
#define QOS_CLASS_HOSTFS_H
#include <stdint.h>
#define QOS_HOSTFS_OPS_VERSION 1u
#define HOSTFS_CHUNK 1024u
enum { HOSTFS_READ = 1, HOSTFS_WRITE = 2, HOSTFS_APPEND = 3, HOSTFS_LIST = 4 };
typedef struct qos_hostfs_ops {
  uint32_t version;
  /* 0 ok, 1 refused (reply holds why), -1 no host, -2 no answer in time,
   * -3 the answer was longer than max. READ and LIST take data =
   * offset (4 bytes LE) + most bytes wanted (2 bytes LE). */
  int (*call)(void *st, uint8_t op, const uint8_t *path, uint32_t plen, const uint8_t *data, uint32_t dlen,
              uint8_t *reply, uint32_t max, uint32_t *len);
} qos_hostfs_ops;
#endif
