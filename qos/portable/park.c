/* OS sleep/wake mechanism for the freestanding app's scheduler.
 * The app chooses runnable actors and timer deadlines in its own runtime.
 * A latched bell and one mutex cover clear/check/wait without a lost wake.
 * A 20 ms fallback matches the Unix runtime: a missed external wake source
 * costs bounded latency, not a permanently stranded worker. */
#ifdef __APPLE__
#define _DARWIN_C_SOURCE 1
#endif
#include "park.h"
#include <pthread.h>
#include <stdlib.h>
#include <time.h>
#include <errno.h>
#include <stdint.h>

typedef struct {
  pthread_mutex_t mutex;
  pthread_cond_t changed;
  int bell;
  uint64_t deadline;
} park_t;
static park_t parks[QOSP_MAXHARTS];
static pthread_once_t once = PTHREAD_ONCE_INIT;
static void require(int result) { if (result) abort(); }
static uint64_t now_ticks(void) {
  struct timespec ts;
  require(clock_gettime(CLOCK_MONOTONIC, &ts));
  return (uint64_t)ts.tv_sec * 10000000 + (uint64_t)ts.tv_nsec / 100;
}
static void init(void) {
  pthread_condattr_t attr;
  require(pthread_condattr_init(&attr));
#ifndef __APPLE__
  require(pthread_condattr_setclock(&attr, CLOCK_MONOTONIC));
#endif
  for (unsigned i = 0; i < QOSP_MAXHARTS; i++) {
    require(pthread_mutex_init(&parks[i].mutex, NULL));
    require(pthread_cond_init(&parks[i].changed, &attr));
  }
  require(pthread_condattr_destroy(&attr));
}
static park_t *get(uint64_t hart) {
  if (hart >= QOSP_MAXHARTS) abort();
  require(pthread_once(&once, init));
  return &parks[hart];
}
void qosp_hart_wait(uint64_t hart) {
  park_t *p = get(hart);
  require(pthread_mutex_lock(&p->mutex));
  uint64_t cap = now_ticks() + 200000; /* bounded fallback: 20 ms */
  while (!p->bell) {
    uint64_t now = now_ticks();
    uint64_t until = p->deadline && p->deadline < cap ? p->deadline : cap;
    if (now >= until) break;
    int result;
#ifdef __APPLE__
    uint64_t left = until - now;
    struct timespec time = {(time_t)(left / 10000000), (long)(left % 10000000) * 100};
    result = pthread_cond_timedwait_relative_np(&p->changed, &p->mutex, &time);
#else
    struct timespec time = {(time_t)(until / 10000000), (long)(until % 10000000) * 100};
    result = pthread_cond_timedwait(&p->changed, &p->mutex, &time);
#endif
    if (result && result != ETIMEDOUT) abort();
  }
  if (p->deadline && now_ticks() >= p->deadline) p->deadline = 0;
  p->bell = 0;
  require(pthread_mutex_unlock(&p->mutex));
}
void qosp_hart_ring(uint64_t hart) {
  park_t *p = get(hart);
  require(pthread_mutex_lock(&p->mutex));
  p->bell = 1;
  require(pthread_cond_signal(&p->changed));
  require(pthread_mutex_unlock(&p->mutex));
}
void qosp_hart_clear(uint64_t hart) {
  park_t *p = get(hart);
  require(pthread_mutex_lock(&p->mutex));
  p->bell = 0;
  require(pthread_mutex_unlock(&p->mutex));
}
void qosp_hart_timer_park(uint64_t hart) {
  park_t *p = get(hart);
  require(pthread_mutex_lock(&p->mutex));
  p->deadline = 0;
  require(pthread_mutex_unlock(&p->mutex));
}
void qosp_hart_timer_arm(uint64_t hart, uint64_t ticks) {
  park_t *p = get(hart);
  require(pthread_mutex_lock(&p->mutex));
  uint64_t now = now_ticks();
  if (!ticks) ticks = 1;
  p->deadline = ticks > UINT64_MAX - now ? UINT64_MAX : now + ticks;
  require(pthread_cond_signal(&p->changed));
  require(pthread_mutex_unlock(&p->mutex));
}
