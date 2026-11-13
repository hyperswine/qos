/* blk_raw.c -- the hosted disk tier (blk_raw.h): qosp.disk as pages.
 *
 * The whole file is mechanism; the numbers are the only decisions:
 *   - pread/pwrite carry their own offsets, so concurrent READS from
 *     any hart thread race against nothing.  Writes are serialized
 *     above by the storage actor being ONE actor (the same single-
 *     writer rule that keeps append-only sound on virt); one-time initialization
 *     publishes the open disk to every caller.
 *   - a short read past a fresh sparse file's materialized extent is
 *     still zeros by contract, so reads zero-fill the tail rather
 *     than failing: an unwritten page IS a zero page.
 *
 * Log lines go through qos_hostlog (the unified log plane): once the
 * app registers its sink, the disk's open story is browsable at
 * /logs/host like every other host-side boot fact. */
#include "blk_raw.h"
#include "../../qos/appside/qos_abi.h"
#include "hostlog.h"

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdlib.h>
#ifdef QOS_BLK_TEST
#include <stdio.h>
#endif
#include <string.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <sys/file.h>
#include <limits.h>
#include <time.h>
#include <unistd.h>

static pthread_once_t disk_once = PTHREAD_ONCE_INIT;
static int blk_fd = -1;
static int blk_dir_fd = -1;
static int blk_name_synced;
static uint64_t blk_npages;

static void open_disk(void) {
  const char *path = getenv("FPR_DISK");
  if (!path || !*path) path = "qosp.disk";

  /* All Portable disk owners use a nonblocking exclusive inode lock.
   * The installed CLI can pass the same locked open-file description so
   * validation-to-launch has no unlock/reopen race. */
  int fd = -1;
  const char *passed = getenv("FPR_DISK_LOCK_FD");
  if (passed && *passed) {
    char *end = NULL;
    errno = 0;
    long inherited = strtol(passed, &end, 10);
    if (!errno && end && !*end && inherited >= 3 && inherited <= INT_MAX) {
      struct stat held, named;
      if (!fstat((int)inherited, &held) && !stat(path, &named) &&
          held.st_dev == named.st_dev && held.st_ino == named.st_ino && S_ISREG(held.st_mode)) {
        fd = fcntl((int)inherited, F_DUPFD_CLOEXEC, 3);
        if (fd >= 0) {
          close((int)inherited);
          /* A later exec must not receive a stale descriptor number. */
          unsetenv("FPR_DISK_LOCK_FD");
        }
      }
    }
    if (fd < 0) {
      qos_hostlog("blk: invalid inherited disk lock -- refusing disk");
      return;
    }
  } else {
    fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0644);
  }
  if (fd < 0) {
    qos_hostlog("blk: cannot open %s (%s) -- no disk", path, strerror(errno));
    return;
  }

  if (flock(fd, LOCK_EX | LOCK_NB) < 0) {
    qos_hostlog("blk: disk in use or lock unavailable: %s (%s)", path, strerror(errno));
    close(fd);
    return;
  }

  /* A first durable commit must also make a newly created backing file's
   * name durable.  Keep this descriptor with the file; changing FPR_DISK
   * after setup must not send the flush to a different directory. */
  const char *slash = strrchr(path, '/');
  size_t parent_len = slash ? (size_t)(slash - path) : 0;
  char *parent = malloc(parent_len + 2);
  if (!parent) { close(fd); return; }
  if (!slash) { parent[0] = '.'; parent[1] = 0; }
  else if (!parent_len) { parent[0] = '/'; parent[1] = 0; }
  else { memcpy(parent, path, parent_len); parent[parent_len] = 0; }
  int dir_fd = open(parent, O_RDONLY | O_DIRECTORY);
  free(parent);
  if (dir_fd < 0) {
    qos_hostlog("blk: cannot open parent of %s (%s) -- no durable disk", path, strerror(errno));
    close(fd);
    return;
  }

  struct stat st;
  if (fstat(fd, &st) < 0) {
    qos_hostlog("blk: cannot stat %s (%s) -- no disk", path, strerror(errno));
    close(fd);
    close(dir_fd);
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
      close(dir_fd);
      return;
    }
    qos_hostlog("blk: %s created, %llu pages of 4096 bytes", path,
                (unsigned long long)(size / QOS_BLK_PAGE));
  } else {
    qos_hostlog("blk: %s opened, %llu pages of 4096 bytes", path,
                (unsigned long long)(size / QOS_BLK_PAGE));
  }

  blk_fd = fd;
  blk_dir_fd = dir_fd;
  blk_npages = size / QOS_BLK_PAGE;
}

void qos_blkraw_setup(void) {
  pthread_once(&disk_once, open_disk);
}

int64_t qos_blkraw_pages(void) {
  qos_blkraw_setup(); /* idempotent: entries are safe in any order */
  return (int64_t)blk_npages;
}

static int64_t read_pages(uint64_t page, uint64_t count, char *dst) {
#ifdef QOS_BLK_TEST
  /* test-only: a slow disk; QOS_BLK_TEST_DELAY_READS limits it to the
   * first N reads (a device that stalls, then recovers) */
  static unsigned long delayed;
  const char *delay = getenv("QOS_BLK_TEST_DELAY_US");
  const char *limit = getenv("QOS_BLK_TEST_DELAY_READS");
  if (delay && (!limit || __atomic_fetch_add(&delayed, 1, __ATOMIC_RELAXED) < strtoul(limit, 0, 10)))
    usleep((useconds_t)strtoul(delay, 0, 10));
#endif
  qos_blkraw_setup();
  if (blk_fd < 0 || page >= blk_npages || count > blk_npages - page) return -1;
  size_t bytes = count * QOS_BLK_PAGE;
  for (size_t got = 0; got < bytes;) {
    ssize_t n = pread(blk_fd, dst + got, bytes - got, (off_t)(page * QOS_BLK_PAGE + got));
    if (n < 0 && errno == EINTR) continue;
    if (n < 0) return -1;
    if (!n) { memset(dst + got, 0, bytes - got); break; }
    got += (size_t)n;
  }
  return 0;
}

int64_t qos_blkraw_read(uint64_t page, char *dst) { return read_pages(page, 1, dst); }

static int64_t write_pages(uint64_t page, const char *data, uint64_t pages) {
  qos_blkraw_setup();
  if (blk_fd < 0 || page >= blk_npages || pages > blk_npages - page) return -1;
  size_t bytes = pages * QOS_BLK_PAGE;
  for (size_t done = 0; done < bytes;) {
    ssize_t n = pwrite(blk_fd, data + done, bytes - done, (off_t)(page * QOS_BLK_PAGE + done));
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) return -1;
    done += (size_t)n;
  }
  return 0;
}

static const char zero_page[QOS_BLK_PAGE];

/* Advance the vector only when a short write leaves bytes outstanding. */
static int write_spans(uint64_t page, size_t pages, struct iovec *spans, int count) {
  qos_blkraw_setup();
  if (blk_fd < 0 || page >= blk_npages || pages > blk_npages - page) return -1;
  off_t offset = (off_t)(page * QOS_BLK_PAGE);
  size_t remaining = pages * QOS_BLK_PAGE;
  while (count) {
    while (count && !spans->iov_len) { spans++; count--; }
    if (!count) break;
    ssize_t n = pwritev(blk_fd, spans, count, offset);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) return -1;
    if ((size_t)n == remaining) return 0;
    remaining -= (size_t)n;
    offset += n;
    size_t consumed = (size_t)n;
    while (count && consumed >= spans->iov_len) {
      consumed -= spans->iov_len;
      spans++;
      count--;
    }
    if (consumed) {
      spans->iov_base = (char *)spans->iov_base + consumed;
      spans->iov_len -= consumed;
    }
  }
  return 0;
}

int64_t qos_blkraw_write(uint64_t page, const char *src, uint64_t len) {
  if (len > QOS_BLK_PAGE || (len && !src)) return -1;
  if (!len) return write_pages(page, zero_page, 1);
  if (len == QOS_BLK_PAGE)
    return write_pages(page, src, 1) == 0 ? (int64_t)len : -1;
  struct iovec spans[] = {
    {(void *)src, len}, {(void *)zero_page, QOS_BLK_PAGE - len}
  };
  return write_spans(page, 1, spans, 2) == 0 ? (int64_t)len : -1;
}

static int sync_fd(int fd) {
  int rc;
  do { rc = fsync(fd); } while (rc < 0 && errno == EINTR);
  return rc;
}
int64_t qos_blkraw_flush(void) {
#ifdef QOS_BLK_TEST
  /* Test-only fault positions let a filesystem test fail or stall the exact
   * barrier whose acknowledgment it is about to expose. */
  static unsigned long flushes;
  unsigned long ordinal = __atomic_add_fetch(&flushes, 1, __ATOMIC_RELAXED);
  if (getenv("QOS_BLK_TEST_TRACE_FLUSH")) fprintf(stderr, "[blk-test] flush %lu\n", ordinal);
  const char *fail = getenv("QOS_BLK_TEST_FAIL_FLUSH_AT");
  const char *delay = getenv("QOS_BLK_TEST_FLUSH_DELAY_US");
  const char *at = getenv("QOS_BLK_TEST_FLUSH_DELAY_AT");
  if (delay && (!at || !strtoul(at, 0, 10) || ordinal == strtoul(at, 0, 10)))
    usleep((useconds_t)strtoul(delay, 0, 10));
  if (fail && ordinal == strtoul(fail, 0, 10)) { errno = EIO; return -1; }
#endif
  qos_blkraw_setup();
  if (blk_fd < 0 || blk_dir_fd < 0) return -1;
#ifdef F_FULLFSYNC
  /* macOS fsync need not flush a drive's volatile cache.  Where the host
   * offers the stronger operation, a refusal is an error, not a successful
   * durability acknowledgment with weaker semantics. */
  int rc;
  do { rc = fcntl(blk_fd, F_FULLFSYNC); } while (rc < 0 && errno == EINTR);
  if (rc < 0) return -1;
#else
  if (sync_fd(blk_fd) < 0) return -1;
#endif
  /* The backing file stays open and the disk worker only overwrites its
   * contents. Persist its directory entry once per open, retrying errors. */
  if (!__atomic_load_n(&blk_name_synced, __ATOMIC_ACQUIRE)) {
    if (sync_fd(blk_dir_fd) < 0) return -1;
    __atomic_store_n(&blk_name_synced, 1, __ATOMIC_RELEASE);
  }
  return 0;
}

/* One host worker serves the disk. No actor-stack or arena pointers cross
 * this boundary. Two references: caller and queue/worker. Killing a waiting
 * actor (or a caller giving up at its deadline) releases the caller
 * reference; the worker finishes and frees its own -- the page buffer lives
 * until the host call that may still write it has returned.
 *
 * The physical queue has a hard bound of 64 queued+running jobs, including
 * jobs whose actors have abandoned them. Caller cancellation cannot release
 * an admission slot until the worker finishes the host operation.
 * When the worker is STALLED -- the job it is running, or the oldest one
 * waiting, has been in the system longer than the deadline -- a new
 * submission is REFUSED (NULL) instead of joining a queue that is not
 * draining. $QOS_BLK_DEADLINE_MS sets the
 * deadline (default 5000, the virt driver's). */
typedef struct blk_job {
  struct blk_job *next;
  unsigned refs, admissions;
  uint64_t page, len;
  unsigned short header_bytes, payload_bytes;
  int operation;
  int64_t result;
  uint64_t submitted; /* monotonic ns */
  char data[];
} blk_job;
static pthread_mutex_t job_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t job_cv = PTHREAD_COND_INITIALIZER;
static pthread_once_t worker_once = PTHREAD_ONCE_INIT;
static blk_job *job_head, *job_tail;
static int worker_ok;
enum { BLK_MAX_PENDING = 64 };
/* Writers serialize under job_mu. Atomic snapshots also let a writer refuse
 * an already-full queue before allocating and copying its input. */
static unsigned job_count;
static uint64_t running_since; /* ns the worker's current job started; 0 idle (job_mu) */
static uint64_t deadline_ns;
static uint64_t mono_ns(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
void qos_blkraw_release(void *p) {
  blk_job *j = p;
  if (__atomic_fetch_sub(&j->refs, 1, __ATOMIC_RELEASE) == 1) {
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    free(j);
  }
}
/* Caller holds job_mu. Flushes can share a barrier only while adjacent. */
static blk_job *take_batch(unsigned *count) {
  blk_job *first = job_head;
  *count = first->admissions;
  job_head = first->next;
  first->next = NULL;
  if (!job_head) job_tail = NULL;
  running_since = mono_ns();
  return first;
}
static void *disk_worker(void *unused) {
  (void)unused;
  blk_job *retired = NULL;
  pthread_mutex_lock(&job_mu);
  for (;;) {
    while (!job_head) pthread_cond_wait(&job_cv, &job_mu);
    unsigned batch;
    blk_job *j = take_batch(&batch);
    pthread_mutex_unlock(&job_mu);
    if (retired) {
      qos_blkraw_release(retired);
      retired = NULL;
    }
    int64_t result;
    switch (j->operation) {
    case QOS_BLK_FLUSH: result = qos_blkraw_flush(); break;
    case QOS_BLK_RECORD: {
      if (!j->payload_bytes) {
        result = qos_blkraw_write(j->page, j->data, j->header_bytes) < 0 ? -1 : 0;
        break;
      }
      if (j->header_bytes + j->payload_bytes == j->len * QOS_BLK_PAGE) {
        result = write_pages(j->page, j->data, j->len);
        break;
      }
      struct iovec spans[] = {
        {j->data, j->header_bytes},
        {(void *)zero_page, QOS_BLK_PAGE - j->header_bytes},
        {j->data + j->header_bytes, j->payload_bytes},
        {(void *)zero_page, (j->len - 1) * QOS_BLK_PAGE - j->payload_bytes}
      };
      result = write_spans(j->page, j->len, spans, 4);
      break;
    }
    case QOS_BLK_WRITE:
      result = qos_blkraw_write(j->page, j->data, j->len);
      break;
    default:
      result = read_pages(j->page, j->len, j->data);
    }
    pthread_mutex_lock(&job_mu);
    running_since = 0;
    unsigned remaining = __atomic_load_n(&job_count, __ATOMIC_RELAXED) - batch;
    __atomic_store_n(&job_count, remaining, __ATOMIC_RELAXED);
    __atomic_store_n(&j->result, result, __ATOMIC_RELEASE);
    if (job_head) retired = j;
    else qos_blkraw_release(j);
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
static blk_job *allocate_job(uint64_t page, uint64_t len, int operation, size_t bytes) {
  blk_job *j = malloc(sizeof *j + bytes);
  if (j) {
    j->next = NULL;
    j->refs = 2;
    j->admissions = 1;
    j->operation = operation;
    j->page = page;
    j->len = len;
    /* Completed operations return -1 or a nonnegative byte count. */
    j->result = INT64_MIN;
  }
  return j;
}
void *qos_blkraw_submit(uint64_t page, const char *src, uint64_t len, int operation) {
  if (operation < QOS_BLK_READ || operation > QOS_BLK_RECORD ||
      (operation == QOS_BLK_RANGE && (src || !len || len > 8)) ||
      len > QOS_BLK_PAGE || (operation == QOS_BLK_WRITE && len && !src) ||
      (operation == QOS_BLK_FLUSH && (page || src || len))) return 0;
  const qos_blk_record_t *record = (const qos_blk_record_t *)src;
  if (operation == QOS_BLK_RECORD &&
      (!record || !record->header || !record->payload || record->header_bytes > QOS_BLK_PAGE ||
       record->payload_bytes > 7 * QOS_BLK_PAGE ||
       len != 1 + (record->payload_bytes + QOS_BLK_PAGE - 1) / QOS_BLK_PAGE)) return 0;
  if (operation == QOS_BLK_READ) {
    operation = QOS_BLK_RANGE;
    len = 1;
  }
  pthread_once(&worker_once, start_worker);
  if (!worker_ok) return 0;
  uint64_t pages = operation == QOS_BLK_FLUSH ? 0 : 1;
  if (operation == QOS_BLK_RANGE || operation == QOS_BLK_RECORD) pages = len;
  size_t buffer_bytes = operation == QOS_BLK_WRITE ? len : pages * QOS_BLK_PAGE;
  if (operation == QOS_BLK_RECORD) buffer_bytes = record->header_bytes + record->payload_bytes;
  blk_job *j = NULL;
  int shareable = operation == QOS_BLK_FLUSH || operation == QOS_BLK_RANGE;
  if (!shareable) {
    if (__atomic_load_n(&job_count, __ATOMIC_RELAXED) >= BLK_MAX_PENDING) return NULL;
    j = allocate_job(page, len, operation, buffer_bytes);
    if (!j) return 0;
    if (operation == QOS_BLK_WRITE && len) {
      memcpy(j->data, src, len);
    }
    if (operation == QOS_BLK_RECORD) {
      j->header_bytes = record->header_bytes;
      j->payload_bytes = record->payload_bytes;
      memcpy(j->data, record->header, j->header_bytes);
      memcpy(j->data + j->header_bytes, record->payload, j->payload_bytes);
    }
  }
  pthread_mutex_lock(&job_mu);
  unsigned admitted = __atomic_load_n(&job_count, __ATOMIC_RELAXED);
  if (admitted >= BLK_MAX_PENDING) {
    pthread_mutex_unlock(&job_mu);
    free(j);
    return NULL;
  }
  uint64_t now = mono_ns();
  if ((running_since && now - running_since > deadline_ns) ||
      (job_head && now - job_head->submitted > deadline_ns)) {
    /* stalled: refuse rather than queue behind a worker that is not draining */
    pthread_mutex_unlock(&job_mu);
    free(j);
    return 0;
  }
  if (shareable) {
    if (job_tail && job_tail->operation == operation && job_tail->page == page && job_tail->len == len) {
      j = job_tail;
      __atomic_fetch_add(&j->refs, 1, __ATOMIC_RELAXED);
      j->admissions++;
      __atomic_store_n(&job_count, admitted + 1, __ATOMIC_RELAXED);
      pthread_mutex_unlock(&job_mu);
      return j;
    }
    j = allocate_job(page, len, operation, buffer_bytes);
    if (!j) {
      pthread_mutex_unlock(&job_mu);
      return NULL;
    }
  }
  j->submitted = now;
  if (job_tail) job_tail->next = j; else job_head = j;
  job_tail = j;
  /* The sole worker checks the FIFO again after every running job. */
  __atomic_store_n(&job_count, admitted + 1, __ATOMIC_RELAXED);
  if (!admitted) pthread_cond_signal(&job_cv);
  pthread_mutex_unlock(&job_mu);
  return j;
}
int qos_blkraw_done(void *p) {
  if (__atomic_load_n(&((blk_job *)p)->result, __ATOMIC_RELAXED) == INT64_MIN) return 0;
  __atomic_thread_fence(__ATOMIC_ACQUIRE);
  return 1;
}
int64_t qos_blkraw_result(void *p, char *dst) {
  blk_job *j = p;
  int64_t result = __atomic_load_n(&j->result, __ATOMIC_ACQUIRE);
  if (result == INT64_MIN) return -1;
  if (result == 0 && dst && j->operation == QOS_BLK_RANGE)
    memcpy(dst, j->data, j->len * QOS_BLK_PAGE);
  return result;
}
