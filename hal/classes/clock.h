/* clock.h -- the CLOCK device class: wall-clock time.
 *
 *   clkNow d   -> String   milliseconds since the Unix epoch, ASCII decimal;
 *                          "" while the time is unknown
 *
 * Decimal text, because epoch milliseconds do not fit a 31-bit RV32 Int. */
#ifndef QOS_CLASS_CLOCK_H
#define QOS_CLASS_CLOCK_H
#include <stdint.h>
#define QOS_CLOCK_OPS_VERSION 1u
typedef struct qos_clock_ops {
  uint32_t version;
  uint32_t (*now)(void *st, char *dst, uint32_t max); /* length, 0 unknown; max >= 21 */
} qos_clock_ops;
#endif
