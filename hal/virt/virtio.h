/* Allocation-free RV64 FP-RISC entries; raw pointers/words, C Ints. */
#ifndef QOS_VIRTIO_H
#define QOS_VIRTIO_H
#include <stdint.h>
extern volatile uint32_t *qos_virtio_probe(long device);
extern volatile uint32_t *qos_virtio_probe_at(void *base, long slots, long stride, long device);
extern long qos_virtio_negotiate(volatile uint32_t *base, uintptr_t low_mask);
extern long qos_virtio_queue(volatile uint32_t *base, long index, long size, void *memory);
extern void qos_virtio_ready(volatile uint32_t *base);
extern long qos_blk_expired(uint64_t since, uint64_t now, uint64_t ticks,
                            uint64_t parks, uint64_t park_limit);
extern long qos_blk_waiting(long state, int completed, int reset_due, int wait_due);
extern long qos_blk_reset_step(uintptr_t status, long attempt, long limit);
extern long qos_blk_budget_valid(long us, long probes, long factor);
#endif
