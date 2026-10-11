/* The real worker and flush implementation, with only its syscalls observed
 * here.  A barrier must neither overtake an admitted write nor let a later
 * write pass it; an abandoned caller must not free a running job. */
#include "blk_raw.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static pthread_mutex_t hook_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t hook_cv = PTHREAD_COND_INITIALIZER;
static int block_write, block_sync, entered, fail_file, fail_dir, interrupt_file;
static char events[64];
static size_t nevents;
static ssize_t observed_write(int fd, const void *src, size_t len, off_t off) {
  pthread_mutex_lock(&hook_mu);
  events[nevents++] = 'W';
  entered = 1;
  pthread_cond_broadcast(&hook_cv);
  while (block_write) pthread_cond_wait(&hook_cv, &hook_mu);
  pthread_mutex_unlock(&hook_mu);
  return pwrite(fd, src, len, off);
}
static int observed_sync(int fd) {
  struct stat st;
  if (fstat(fd, &st)) return -1;
  int dir = S_ISDIR(st.st_mode), error = 0;
  pthread_mutex_lock(&hook_mu);
  events[nevents++] = dir ? 'D' : 'F';
  if (!dir) {
    entered = 1;
    pthread_cond_broadcast(&hook_cv);
    while (block_sync) pthread_cond_wait(&hook_cv, &hook_mu);
  }
  if (dir && fail_dir) { fail_dir = 0; error = EIO; }
  if (!dir && fail_file) { fail_file = 0; error = EIO; }
  if (!dir && interrupt_file) { interrupt_file = 0; error = EINTR; }
  pthread_mutex_unlock(&hook_mu);
  if (error) { errno = error; return -1; }
  return fsync(fd);
}
#define pwrite observed_write
#define fsync observed_sync
#include "../../hal/unix/blk_raw.c"
#undef pwrite
#undef fsync

static int failures;
#define CHECK(c, label) do { if (!(c)) { fprintf(stderr, "FAIL: %s\n", label); failures++; } } while (0)
static void *job(int operation) {
  void *p = qos_blkraw_submit(0, NULL, 0, operation);
  if (!p) { fprintf(stderr, "job refused unexpectedly\n"); exit(1); }
  return p;
}
static int64_t finish(void *p) {
  for (int i = 0; i < 5000 && !qos_blkraw_done(p); i++) usleep(1000);
  if (!qos_blkraw_done(p)) { fprintf(stderr, "job did not finish\n"); exit(1); }
  int64_t r = qos_blkraw_result(p, NULL);
  qos_blkraw_release(p);
  return r;
}
static void wait_entered(void) {
  for (int i = 0; i < 5000; i++) {
    pthread_mutex_lock(&hook_mu);
    int yes = entered;
    pthread_mutex_unlock(&hook_mu);
    if (yes) return;
    usleep(1000);
  }
  fprintf(stderr, "worker never reached syscall hook\n"); exit(1);
}
static void unblock(void) {
  pthread_mutex_lock(&hook_mu);
  block_write = block_sync = 0;
  pthread_cond_broadcast(&hook_cv);
  pthread_mutex_unlock(&hook_mu);
}
int main(void) {
  char folder[] = "/tmp/qos-blkflush-XXXXXX", path[128];
  if (!mkdtemp(folder)) return 1;
  snprintf(path, sizeof path, "%s/disk", folder);
  setenv("FPR_DISK", path, 1);
  setenv("QOS_BLK_DEADLINE_MS", "20", 1);
  CHECK(qos_blkraw_pages() == 2048, "fresh file initialized");

  block_write = 1;
  void *before = qos_blkraw_submit(0, "A", 1, QOS_BLK_WRITE);
  void *barrier = job(QOS_BLK_FLUSH);
  void *after = qos_blkraw_submit(1, "B", 1, QOS_BLK_WRITE);
  CHECK(before && after, "writes admitted around barrier");
  wait_entered();
  CHECK(!qos_blkraw_done(barrier) && !qos_blkraw_done(after), "barrier and later write wait for previous write");
  unblock();
  CHECK(finish(before) == 1 && finish(barrier) == 0 && finish(after) == 1, "FIFO work completed");
  CHECK(nevents == 4 && !memcmp(events, "WFDW", 4), "write, file sync, directory sync, later write order");

  fail_file = 1;
  CHECK(finish(job(QOS_BLK_FLUSH)) == -1, "file sync failure propagated");
  fail_dir = 1;
  CHECK(finish(job(QOS_BLK_FLUSH)) == -1, "directory sync failure propagated");
  interrupt_file = 1;
  CHECK(finish(job(QOS_BLK_FLUSH)) == 0, "interrupted sync retried");

  entered = 0; block_sync = 1;
  void *abandoned = job(QOS_BLK_FLUSH);
  wait_entered();
  qos_blkraw_release(abandoned); /* no caller reference while fsync runs */
  void *marker = job(QOS_BLK_READ);
  unblock();
  CHECK(finish(marker) == 0, "abandoned flush stayed alive until worker completion");

  /* Cancellation frees only the caller reference. Keep a physical barrier
   * blocked, abandon every admitted job, and prove those jobs still occupy
   * the entire fixed admission budget until the worker drains them. */
  pthread_mutex_lock(&job_mu);
  uint64_t saved_deadline = deadline_ns;
  deadline_ns = UINT64_MAX;
  pthread_mutex_unlock(&job_mu);
  entered = 0; block_sync = 1;
  void *physical[BLK_MAX_PENDING];
  physical[0] = job(QOS_BLK_FLUSH);
  wait_entered();
  for (unsigned i = 1; i < BLK_MAX_PENDING; i++) physical[i] = job(QOS_BLK_READ);
  CHECK(!qos_blkraw_submit(0, NULL, 0, QOS_BLK_READ), "physical queue refuses the 65th queued+running job");
  for (unsigned i = 0; i < BLK_MAX_PENDING; i++) qos_blkraw_release(physical[i]);
  CHECK(!qos_blkraw_submit(0, NULL, 0, QOS_BLK_FLUSH), "abandonment cannot release physical admission slots");
  unblock();
  for (int i = 0; i < 5000; i++) {
    pthread_mutex_lock(&job_mu);
    unsigned count = job_count;
    pthread_mutex_unlock(&job_mu);
    if (!count) break;
    usleep(1000);
  }
  CHECK(finish(job(QOS_BLK_READ)) == 0, "physical admission recovers after abandoned work drains");
  pthread_mutex_lock(&job_mu);
  deadline_ns = saved_deadline;
  pthread_mutex_unlock(&job_mu);

  setenv("QOS_BLK_TEST_FAIL_FLUSH_AT", "7", 1);
  CHECK(finish(job(QOS_BLK_FLUSH)) == -1, "ordinal flush fault hook propagated");
  unsetenv("QOS_BLK_TEST_FAIL_FLUSH_AT");
  setenv("QOS_BLK_TEST_FLUSH_DELAY_AT", "8", 1);
  setenv("QOS_BLK_TEST_FLUSH_DELAY_US", "200000", 1);
  void *delayed = job(QOS_BLK_FLUSH);
  usleep(60000);
  CHECK(!qos_blkraw_done(delayed), "delayed barrier remains pending");
  CHECK(!qos_blkraw_submit(0, NULL, 0, QOS_BLK_READ), "stalled flush refuses new work after deadline");
  qos_blkraw_release(delayed);
  usleep(200000);
  CHECK(finish(job(QOS_BLK_FLUSH)) == 0, "worker resumes after abandoned delayed flush");

  CHECK(!qos_blkraw_submit(0, NULL, 0, 3), "unknown operation refused");
  CHECK(!qos_blkraw_submit(1, NULL, 0, QOS_BLK_FLUSH), "flush with page argument refused");
  CHECK(!qos_blkraw_submit(0, "x", 1, QOS_BLK_FLUSH), "flush with payload refused");
  unlink(path); rmdir(folder);
  if (!failures) puts("blkflush: FIFO file/directory barrier, errors, EINTR, abandonment, physical queue bound, stalled refusal and recovery: PASS");
  return failures ? 1 : 0;
}
