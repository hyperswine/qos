/* Compile the real worker with a controlled pread, so queue abandonment and
 * copied write buffers are tested without timing races or real disk latency. */
#include <assert.h>
#include <pthread.h>
#include <unistd.h>
#include <stdarg.h>
#include <stdio.h>
static pthread_mutex_t probe_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t probe_cv = PTHREAD_COND_INITIALIZER;
static int probe_entered, probe_release;
static ssize_t probe_pread(int fd, void *buf, size_t n, off_t off) {
  pthread_mutex_lock(&probe_mu);
  probe_entered = 1; pthread_cond_broadcast(&probe_cv);
  while (!probe_release) pthread_cond_wait(&probe_cv, &probe_mu);
  pthread_mutex_unlock(&probe_mu);
  return pread(fd, buf, n, off);
}
#include "../../hal/unix/hostlog.h"
void qos_hostlog(const char *fmt, ...) { (void)fmt; }
#define pread probe_pread
#include "../../hal/unix/blk_raw.c"
#undef pread
static void wait_done(void *p) { while (!qos_blkraw_done(p)) usleep(100); }
static void block_next(void) {
  pthread_mutex_lock(&probe_mu); probe_entered = 0; probe_release = 0; pthread_mutex_unlock(&probe_mu);
}
static void wait_entered(void) {
  pthread_mutex_lock(&probe_mu);
  while (!probe_entered) pthread_cond_wait(&probe_cv, &probe_mu);
  pthread_mutex_unlock(&probe_mu);
}
static void release_probe(void) {
  pthread_mutex_lock(&probe_mu); probe_release = 1;
  pthread_cond_broadcast(&probe_cv); pthread_mutex_unlock(&probe_mu);
}
int main(void) {
  setenv("QOS_BLK_DEADLINE_MS", "200", 1); /* read once, at the worker's start */
  void *read = qos_blkraw_submit(0, 0, 0, 0); assert(read);
  pthread_mutex_lock(&probe_mu);
  while (!probe_entered) pthread_cond_wait(&probe_cv, &probe_mu);
  pthread_mutex_unlock(&probe_mu);
  assert(!qos_blkraw_done(read));
  qos_blkraw_release(read); /* caller dies while worker is blocked */
  char data[4096]; memset(data, 'x', sizeof data);
  void *write = qos_blkraw_submit(1, data, sizeof data, 1); assert(write);
  memset(data, 'y', sizeof data); /* source is no longer borrowed */
  void *bad = qos_blkraw_submit(UINT64_MAX, 0, 0, 0); assert(bad);
  pthread_mutex_lock(&probe_mu); probe_release = 1;
  pthread_cond_broadcast(&probe_cv); pthread_mutex_unlock(&probe_mu);
  wait_done(write); assert(qos_blkraw_result(write, 0) == 4096);
  qos_blkraw_release(write);
  wait_done(bad); assert(qos_blkraw_result(bad, 0) == -1);
  qos_blkraw_release(bad);
  read = qos_blkraw_submit(1, 0, 0, 0); assert(read);
  wait_done(read); assert(qos_blkraw_result(read, data) == 0);
  for (unsigned i = 0; i < sizeof data; ++i) assert(data[i] == 'x');
  qos_blkraw_release(read);
  assert(!qos_blkraw_submit(0, data, 4097, 1));
  /* a STALLED worker: its job outlives the deadline, and new work is refused
   * instead of queueing behind it; once it drains, work is accepted again */
  block_next();
  void *stuck = qos_blkraw_submit(1, 0, 0, 0); assert(stuck);
  wait_entered();
  void *early = qos_blkraw_submit(2, 0, 0, 0); assert(early); /* within the deadline: queued */
  usleep(300000);
  assert(!qos_blkraw_submit(3, 0, 0, 0)); /* past it: refused */
  assert(!qos_blkraw_submit(3, data, 16, 1));
  qos_blkraw_release(stuck); /* its caller gave up at the deadline */
  release_probe();
  wait_done(early); assert(qos_blkraw_result(early, data) == 0);
  qos_blkraw_release(early);
  void *again = qos_blkraw_submit(1, 0, 0, 0); assert(again);
  wait_done(again); assert(qos_blkraw_result(again, data) == 0);
  qos_blkraw_release(again);
  puts("disk worker: abandoned request, owned buffer, completion and refusal: PASS");
  puts("disk worker: a stalled worker refuses new requests past the deadline, accepts again once drained: PASS");
}
