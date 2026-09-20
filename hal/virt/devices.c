/* devices.c -- QOS Native's devices on the virt board.
 *
 * The compiler tree's machine layer names only uart and clint
 * (hal/virt/hal.c).  The virtio devices are QOS's drivers, so QOS names them:
 * `device "net"` and `device "blk"` resolve here, through the machine layer's
 * weak hal_devtable_ext hook, and bring the driver up on first use. */
#include "devtable.h"

#define VIRTIO0_BASE 0x10001000UL

extern void net_setup(void); /* net.c: probe virtio slots, bring up queues */
extern void blk_setup(void); /* blk.c: probe virtio slots, bring up disk queue */

static const devtable_entry_t qos_devices[] = {
  {"net", {T_DEVICE, 0, VIRTIO0_BASE}, net_setup, NULL},
  {"blk", {T_DEVICE, 0, VIRTIO0_BASE}, blk_setup, NULL},
};

const devtable_entry_t *hal_devtable_ext(uw *count) {
  *count = sizeof qos_devices / sizeof qos_devices[0];
  return qos_devices;
}
