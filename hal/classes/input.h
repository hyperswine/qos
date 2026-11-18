/* input.h -- the INPUT device class: key (and later pointer) events.
 *
 *   inRead d   -> String   the events waiting now, 4 bytes each:
 *                          [kind, code lo, code hi, value]; kind 1 = key
 *                          (evdev key codes; value 1 down, 0 up, 2 repeat)
 *
 * A driver never blocks; events stay queued until read, and a full queue
 * drops the newest events and counts them. */
#ifndef QOS_CLASS_INPUT_H
#define QOS_CLASS_INPUT_H
#include <stdint.h>
#define QOS_INPUT_OPS_VERSION 1u
#define QOS_INPUT_EVENT 4u
typedef struct qos_input_ops {
  uint32_t version;
  uint32_t (*read)(void *st, uint8_t *dst, uint32_t max); /* whole events only */
} qos_input_ops;
#endif
