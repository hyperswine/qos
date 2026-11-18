/* qlink_dev.h -- device class instances carried by a qlink port
 * (hal/link/qlink_port.h): one state type, five ops tables. A board names
 * them in its manifest with the port they ride on:
 *   {"name": "clk0", "driver": "qlink_clock", "params": {"port": "&qlink_board_port"}}
 */
#ifndef QOS_DRIVER_QLINK_DEV_H
#define QOS_DRIVER_QLINK_DEV_H
#include "../link/qlink_port.h"
#include "../classes/console.h"
#include "../classes/input.h"
#include "../classes/clock.h"
#include "../classes/hostfs.h"
#include "../classes/audio.h"

/* port: the link; init: starts it on first use, for a board with no boot
 * hook of its own (NULL where the board's HAL starts it, as Spectre's does) */
typedef struct qlink_dev { qport_t *port; void (*init)(void); } qlink_dev_t;
extern qport_t qlink_board_port; /* the board's link (its serial backend defines it) */
void qlink_uart16550_init(void);  /* hal/link/qlink_uart16550.c: a 16550 backend */

extern const qos_console_ops qlink_console_ops;
extern const qos_input_ops qlink_input_ops;
extern const qos_clock_ops qlink_clock_ops;
extern const qos_hostfs_ops qlink_hostfs_ops;
extern const qos_audio_ops qlink_audio_ops;
#endif
