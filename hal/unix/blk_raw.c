/* blk_raw.c -- the hosted disk tier (blk_raw.h): qosp.disk as pages.
 *
 * The whole file is mechanism; the numbers are the only decisions:
 *   - pread/pwrite carry their own offsets, so concurrent READS from
 *     any hart thread race against nothing.  Writes are serialized
 *     above by the storage actor being ONE actor (the same single-
 *     writer rule that keeps append-only sound on virt); the mutex
 *     here guards only first-open against two harts discovering the
 *     device at once.
 *   - a short read past a fresh sparse file's materialized extent is
 *     still zeros by contract, so reads zero-fill the tail rather
 *     than failing: an unwritten page IS a zero page.
 *
 * Log lines go through qos_hostlog (the unified log plane): once the
 * app registers its sink, the disk's open story is browsable at
 * /logs/host like every other host-side boot fact. */
#include "blk_raw.h"
#include "hostlog.h"

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static pthread_mutex_t blk_mu = PTHREAD_MUTEX_INITIALIZER;
static int blk_fd = -1;
static int blk_tried;
static uint64_t blk_npages;

static void blk_open_locked(void) {
  if (blk_tried) return;
  blk_tried = 1;

  const char *path = getenv("FPR_DISK");
  if (!path || !*path) path = "qosp.disk";

  int fd = open(path, O_RDWR | O_CREAT, 0644);
  if (fd < 0) {
    qos_hostlog("blk: cannot open %s (%s) -- no disk", path, strerror(errno));
    return;
  }

  struct stat st;
  if (fstat(fd, &st) < 0) {
    qos_hostlog("blk: cannot stat %s (%s) -- no disk", path, strerror(errno));
    close(fd);
    return;
  }

  uint64_t size = (uint64_t)st.st_size;
  if (size < QOS_BLK_PAGE) {
    /* fresh (or degenerate) file: size it.  ftruncate gives a sparse
     * zero-filled extent -- an unformatted disk, exactly what a blank
     * qcow-less virtio image is to virt's blk.c. */
    uint64_t mb = 8;
    const char *mbs = getenv("FPR_DISK_MB");
    if (mbs && *mbs) {
      unsigned long v = strtoul(mbs, 0, 10);
      if (v >= 1 && v <= 4096) mb = v;
    }
    size = mb << 20;
    if (ftruncate(fd, (off_t)size) < 0) {
      qos_hostlog("blk: cannot size %s to %lluMB (%s) -- no disk", path,
                  (unsigned long long)mb, strerror(errno));
      close(fd);
      return;
    }
    qos_hostlog("blk: %s created, %llu pages of 4096 bytes", path,
                (unsigned long long)(size / QOS_BLK_PAGE));
  } else {
    qos_hostlog("blk: %s opened, %llu pages of 4096 bytes", path,
                (unsigned long long)(size / QOS_BLK_PAGE));
  }

  blk_fd = fd;
  blk_npages = size / QOS_BLK_PAGE;
}

void qos_blkraw_setup(void) {
  pthread_mutex_lock(&blk_mu);
  blk_open_locked();
  pthread_mutex_unlock(&blk_mu);
}

int64_t qos_blkraw_pages(void) {
  qos_blkraw_setup(); /* idempotent: entries are safe in any order */
  return (int64_t)blk_npages;
}

int64_t qos_blkraw_read(uint64_t page, char *dst) {
#ifdef QOS_BLK_TEST
  /* test-only: a slow disk; QOS_BLK_TEST_DELAY_READS limits it to the
   * first N reads (a device that stalls, then recovers) */
  static unsigned long delayed;
  const char *delay = getenv("QOS_BLK_TEST_DELAY_US");
  const char *count = getenv("QOS_BLK_TEST_DELAY_READS");
  if (delay && (!count || __atomic_fetch_add(&delayed, 1, __ATOMIC_RELAXED) < strtoul(count, 0, 10)))
    usleep((useconds_t)strtoul(delay, 0, 10));
#endif
  qos_blkraw_setup();
  if (blk_fd < 0 || page >= blk_npages) return -1;
  ssize_t n = pread(blk_fd, dst, QOS_BLK_PAGE, (off_t)(page * QOS_BLK_PAGE));
  if (n < 0) return -1;
  /* sparse tail: unwritten bytes are zero by contract */
  if ((uint64_t)n < QOS_BLK_PAGE) memset(dst + n, 0, QOS_BLK_PAGE - (uint64_t)n);
  return 0;
}

int64_t qos_blkraw_write(uint64_t page, const char *src, uint64_t len) {
  qos_blkraw_setup();
  if (blk_fd < 0 || page >= blk_npages || len > QOS_BLK_PAGE) return -1;
  char buf[QOS_BLK_PAGE];
  memcpy(buf, src, len);
  memset(buf + len, 0, QOS_BLK_PAGE - len); /* whole pages, zero-padded */
  ssize_t n = pwrite(blk_fd, buf, QOS_BLK_PAGE, (off_t)(page * QOS_BLK_PAGE));
  return n == (ssize_t)QOS_BLK_PAGE ? (int64_t)len : -1;
}

/* One host worker serves the disk. No actor-stack or arena pointers cross
 * this boundary. Two references: caller and queue/worker. Killing a waiting
 * actor (or a caller giving up at its deadline) releases the caller
 * reference; the worker finishes and frees its own -- the page buffer lives
 * until the host call that may still write it has returned.
 *
 * THE BOUND (2026-10-01): the queue is bounded by time, not by a count.
 * When the worker is STALLED -- the job it is running, or the oldest one
 * waiting, has been in the system longer than the deadline -- a new
 * submission is REFUSED (NULL) instead of joining a queue that is not
 * draining.  Callers are themselves deadline-bound, so the queue holds at
 * most what arrives within one deadline.  $QOS_BLK_DEADLINE_MS sets the
 * deadline (default 5000, the virt driver's). */
typedef struct blk_job {
  struct blk_job *next;
  unsigned refs, done;
  uint64_t page, len;
  int write;
  int64_t result;
  uint64_t submitted; /* monotonic ns */
  char data[QOS_BLK_PAGE];
} blk_job;
static pthread_mutex_t job_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t job_cv = PTHREAD_COND_INITIALIZER;
static pthread_once_t worker_once = PTHREAD_ONCE_INIT;
static blk_job *job_head, *job_tail;
static int worker_ok;
static uint64_t running_since; /* ns the worker's current job started; 0 idle (job_mu) */
static uint64_t deadline_ns;
static uint64_t mono_ns(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
void qos_blkraw_release(void *p) {
  blk_job *j = p;
  if (__atomic_sub_fetch(&j->refs, 1, __ATOMIC_ACQ_REL) == 0) free(j);
}
static void *disk_worker(void *unused) {
  (void)unused;
  for (;;) {
    pthread_mutex_lock(&job_mu);
    while (!job_head) pthread_cond_wait(&job_cv, &job_mu);
    blk_job *j = job_head;
    job_head = j->next;
    if (!job_head) job_tail = 0;
    running_since = mono_ns();
    pthread_mutex_unlock(&job_mu);
    j->result = j->write ? qos_blkraw_write(j->page, j->data, j->len)
                         : qos_blkraw_read(j->page, j->data);
    pthread_mutex_lock(&job_mu);
    running_since = 0;
    pthread_mutex_unlock(&job_mu);
    __atomic_store_n(&j->done, 1, __ATOMIC_RELEASE);
    qos_blkraw_release(j);
  }
  return 0;
}
static void start_worker(void) {
  const char *ms = getenv("QOS_BLK_DEADLINE_MS");
  unsigned long v = ms && *ms ? strtoul(ms, 0, 10) : 0;
  deadline_ns = (uint64_t)(v ? v : 5000) * 1000000ull;
  pthread_t t;
  if (pthread_create(&t, 0, disk_worker, 0) == 0) {
    pthread_detach(t); worker_ok = 1;
  }
}
void *qos_blkraw_submit(uint64_t page, const char *src, uint64_t len, int write) {
  if (len > QOS_BLK_PAGE || (write && len && !src)) return 0;
  pthread_once(&worker_once, start_worker);
  if (!worker_ok) return 0;
  blk_job *j = calloc(1, sizeof *j);
  if (!j) return 0;
  j->refs = 2; j->page = page; j->len = len; j->write = write;
  if (write && len) memcpy(j->data, src, len);
  pthread_mutex_lock(&job_mu);
  uint64_t now = mono_ns();
  j->submitted = now;
  if ((running_since && now - running_since > deadline_ns) ||
      (job_head && now - job_head->submitted > deadline_ns)) {
    /* stalled: refuse rather than queue behind a worker that is not draining */
    pthread_mutex_unlock(&job_mu);
    free(j);
    return 0;
  }
  if (job_tail) job_tail->next = j; else job_head = j;
  job_tail = j;
  pthread_cond_signal(&job_cv);
  pthread_mutex_unlock(&job_mu);
  return j;
}
int qos_blkraw_done(void *p) {
  return __atomic_load_n(&((blk_job *)p)->done, __ATOMIC_ACQUIRE);
}
int64_t qos_blkraw_result(void *p, char *dst) {
  blk_job *j = p;
  if (!qos_blkraw_done(j)) return -1;
  if (!j->write && j->result == 0 && dst) memcpy(dst, j->data, QOS_BLK_PAGE);
  return j->result;
}
