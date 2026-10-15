/* Portable app worker doorbells. Separate from the host runtime's workers. */
#ifndef QOSP_PARK_H
#define QOSP_PARK_H
#include <stdint.h>
#define QOSP_MAXHARTS 64
void qosp_hart_wait(uint64_t hart);
void qosp_hart_ring(uint64_t hart);
void qosp_hart_clear(uint64_t hart);
void qosp_hart_timer_arm(uint64_t hart, uint64_t ticks);
void qosp_hart_timer_park(uint64_t hart);
#endif
