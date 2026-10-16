/* compile.c -- qosp's UNIX-DOMAIN-SOCKET bridge to the host-side fpr
 * compiler server (tools/fprd.py).
 *
 * The app never sees a socket: it calls Sys.compile (std/compile.fpr),
 * the app-side shim submits the request through the HAL table's
 * compile_* entries (ABI v21), and THIS file does the host part --
 * connect to the daemon, frame the request, read the reply.  The
 * compiler stays a host process (GHC-built ./fprc behind the daemon);
 * QOS keeps the policy: what to compile, when, and where the returned
 * assembly or plugin is stored or attached.
 *
 *   socket   $FPRD_SOCK, else /tmp/fprd.sock
 *   frame    4-byte LE length + payload, both directions
 *   request  "<profile>\n<source>" (passed through verbatim; the
 *            daemon whitelists the profile token)
 *   reply    "ok\n<asm or .qa bytes>" | "err\n<message>" -- handed
 *            to the app as it came, the app-side shim parses the
 *            status line
 *
 * A request is WORKER-BACKED, like the disk's (hal/unix/blk_raw.c): the
 * submit copies it and queues it for one host thread, which does the
 * exchange; the app's calling actor parks between polls
 * (appside/entry.c), so a compile that takes seconds holds no hart --
 * the shell and the app it came from keep running (until v21 the
 * exchange ran on the calling hart's thread and froze whatever shared
 * that hart: the shell, on hart 0).  One worker, so requests reach the
 * daemon in order, the way it serves them.
 *
 * Two references, the caller's and the worker's: a caller that is
 * killed (its app closed mid-build) releases its own, and the worker
 * frees the job once the exchange it may still be in has returned.
 *
 * The reply has no size of its own: it is read whole into the job, so a
 * large plugin is never refused for its size (until v21 it had to fit
 * the app's 256 KiB syscall buffer).  What bounds a request is the
 * daemon's (4 MiB of source); what bounds the wait is QOSP_COMPILE_WAIT_S
 * below, derived from the daemon's own deadlines. */
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>

/* fprd.py answers within its own deadlines: a publication is a commit
 * (120 s) then a plugin build (300 s), its longest; a server that has
 * said nothing for longer than that is not going to (-3).  (A test build
 * shortens it: qos/tests-host/compile-check.sh.) */
#ifndef QOSP_COMPILE_WAIT_S
#define QOSP_COMPILE_WAIT_S 450
#endif

static int rd_exact(int fd, void *dst, size_t n) {
  char *p = (char *)dst;
  while (n) {
    ssize_t r = read(fd, p, n);
    if (r <= 0) {
      if (r < 0 && errno == EINTR) continue;
      return r < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) ? -3 : -1;
    }
    p += r;
    n -= (size_t)r;
  }
  return 0;
}

static int wr_all(int fd, const void *src, size_t n) {
  const char *p = (const char *)src;
  while (n) {
    ssize_t r = write(fd, p, n);
    if (r <= 0) {
      if (r < 0 && errno == EINTR) continue;
      return r < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) ? -3 : -1;
    }
    p += r;
    n -= (size_t)r;
  }
  return 0;
}

/* one exchange: the reply's byte count with *reply malloc'd, or -2 no
 * compiler server, -3 the server stopped answering, -1 any other error */
static int64_t exchange(const char *pay, uint64_t plen, char **reply) {
  *reply = 0;
  if (plen > 0xffffffffull) return -1; /* the frame's length is 32 bits */
  const char *path = getenv("FPRD_SOCK");
  if (!path || !path[0]) path = "/tmp/fprd.sock";

  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) return -1;
  struct sockaddr_un sa;
  memset(&sa, 0, sizeof sa);
  sa.sun_family = AF_UNIX;
  if (strlen(path) >= sizeof sa.sun_path) { close(fd); return -1; }
  strcpy(sa.sun_path, path);
  if (connect(fd, (struct sockaddr *)&sa, sizeof sa)) {
    close(fd);
    return -2; /* no compiler server: the app-side shim names it */
  }
  struct timeval tv = { QOSP_COMPILE_WAIT_S, 0 };
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
#ifdef SO_NOSIGPIPE
  { int one = 1; setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one); }
#endif

  unsigned char hdr[4] = { (unsigned char)plen, (unsigned char)(plen >> 8),
                           (unsigned char)(plen >> 16),
                           (unsigned char)(plen >> 24) };
  int w = wr_all(fd, hdr, 4);
  if (!w) w = wr_all(fd, pay, plen);
  if (w) { close(fd); return w; }

  int r = rd_exact(fd, hdr, 4);
  if (r) { close(fd); return r; }
  uint64_t rlen = (uint64_t)hdr[0] | ((uint64_t)hdr[1] << 8) |
                  ((uint64_t)hdr[2] << 16) | ((uint64_t)hdr[3] << 24);
  char *buf = malloc(rlen ? rlen : 1);
  if (!buf) { close(fd); return -1; }
  r = rd_exact(fd, buf, rlen);
  close(fd);
  if (r) { free(buf); return r; }
  *reply = buf;
  return (int64_t)rlen;
}

typedef struct cjob {
  struct cjob *next;
  unsigned refs, done;
  char *pay;
  uint64_t plen;
  char *reply;
  int64_t rlen;
} cjob;
static pthread_mutex_t cj_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cj_cv = PTHREAD_COND_INITIALIZER;
static pthread_once_t cj_once = PTHREAD_ONCE_INIT;
static cjob *cj_head, *cj_tail;
static int cj_ok;

void qosp_compile_release(void *p) {
  cjob *j = p;
  if (__atomic_sub_fetch(&j->refs, 1, __ATOMIC_ACQ_REL) == 0) {
    free(j->pay);
    free(j->reply);
    free(j);
  }
}

static void *compile_worker(void *unused) {
  (void)unused;
  for (;;) {
    pthread_mutex_lock(&cj_mu);
    while (!cj_head) pthread_cond_wait(&cj_cv, &cj_mu);
    cjob *j = cj_head;
    cj_head = j->next;
    if (!cj_head) cj_tail = 0;
    pthread_mutex_unlock(&cj_mu);
    /* an abandoned job (the only reference left is ours) is not sent */
    if (__atomic_load_n(&j->refs, __ATOMIC_ACQUIRE) > 1)
      j->rlen = exchange(j->pay, j->plen, &j->reply);
    else
      j->rlen = -1;
    free(j->pay);
    j->pay = 0;
    __atomic_store_n(&j->done, 1, __ATOMIC_RELEASE);
    qosp_compile_release(j);
  }
  return 0;
}

static void start_worker(void) {
  pthread_t t;
  if (pthread_create(&t, 0, compile_worker, 0) == 0) {
    pthread_detach(t);
    cj_ok = 1;
  }
}

/* NULL: no worker thread, or no memory -- the shim says so */
void *qosp_compile_submit(const char *pay, uint64_t plen) {
  pthread_once(&cj_once, start_worker);
  if (!cj_ok) return 0;
  cjob *j = calloc(1, sizeof *j);
  if (!j) return 0;
  j->pay = malloc(plen ? plen : 1);
  if (!j->pay) { free(j); return 0; }
  memcpy(j->pay, pay, plen);
  j->plen = plen;
  j->refs = 2;
  pthread_mutex_lock(&cj_mu);
  if (cj_tail) cj_tail->next = j; else cj_head = j;
  cj_tail = j;
  pthread_cond_signal(&cj_cv);
  pthread_mutex_unlock(&cj_mu);
  return j;
}

int qosp_compile_done(void *p) {
  return __atomic_load_n(&((cjob *)p)->done, __ATOMIC_ACQUIRE);
}

/* the reply's byte count, *bytes pointing at it until the release; or
 * -2 no compiler server, -3 it stopped answering, -1 other errors (and
 * -1 while the job is still running) */
int64_t qosp_compile_reply(void *p, const char **bytes) {
  cjob *j = p;
  *bytes = 0;
  if (!qosp_compile_done(j)) return -1;
  *bytes = j->reply;
  return j->rlen;
}
