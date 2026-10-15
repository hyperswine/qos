/* Exercise latched notifications, timer waits and the clear/wait race. */
#include "../portable/park.h"
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <sched.h>
static uint64_t us(void) {
  struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}
static atomic_uint turn, done;
static void *waiter(void *unused) {
  (void)unused;
  for (unsigned i=1; i<=2000; i++) {
    qosp_hart_clear(1);
    atomic_store(&turn, i);
    qosp_hart_wait(1);
    atomic_store(&done, i);
  }
  return NULL;
}
int main(void) {
  qosp_hart_ring(0);
  uint64_t start=us(); qosp_hart_wait(0);
  assert(us()-start < 200000); /* notification survives arrival before wait */
  qosp_hart_timer_arm(0, 40000);
  start=us(); qosp_hart_wait(0);
  assert(us()-start >= 3900); /* 10 MHz timer must not wake early */
  qosp_hart_ring(0); qosp_hart_clear(0);
  qosp_hart_timer_arm(0, 40000);
  start=us(); qosp_hart_wait(0);
  assert(us()-start >= 3900); /* clear consumes a previous notification */
  qosp_hart_timer_arm(0, 1); qosp_hart_timer_park(0);
  start=us(); qosp_hart_wait(0);
  assert(us()-start >= 19000); /* cancelled timer leaves the fallback wait */
  pthread_t thread; assert(!pthread_create(&thread, NULL, waiter, NULL));
  start=us();
  for (unsigned i=1; i<=2000; i++) {
    while (atomic_load(&turn) < i) sched_yield();
    qosp_hart_ring(1);
    while (atomic_load(&done) < i) sched_yield();
  }
  assert(!pthread_join(thread, NULL));
  assert(us()-start < 10000000); /* losing each race would cost 40 seconds */
  puts("portable park: latched bell/timer/clear/cancel/2000 races HOLDS");
}
