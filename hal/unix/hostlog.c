/* hostlog.c -- see hostlog.h for the contract. */
#include "hostlog.h"

#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* pending lines from before the app registered its ring: replayed in
 * order at registration.  A rolling window -- if boot somehow emits
 * more than PEND_N lines, the OLDEST drop (stderr kept them all). */
#define PEND_N 32
#define PEND_W 160
static char pend[PEND_N][PEND_W];
static uint64_t pend_seq; /* total ever; live window = last PEND_N */
static void (*g_sink)(const char *line, uint64_t n);
static pthread_mutex_t hl_mu = PTHREAD_MUTEX_INITIALIZER;

void qos_hostlog(const char *fmt, ...) {
  char line[PEND_W];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(line, sizeof line, fmt, ap);
  va_end(ap);
  size_t n = strlen(line);
  while (n && line[n - 1] == '\n') line[--n] = 0; /* ring lines are unterminated */
  /* stderr always: journald keeps its record regardless of the app */
  fprintf(stderr, "%s\n", line);
  pthread_mutex_lock(&hl_mu);
  if (g_sink) {
    void (*s)(const char *, uint64_t) = g_sink;
    pthread_mutex_unlock(&hl_mu);
    s(line, n);
    return;
  }
  memcpy(pend[pend_seq % PEND_N], line, n + 1);
  pend_seq++;
  pthread_mutex_unlock(&hl_mu);
}

#ifndef QOS_CONSOLE_WAIT_MS
#define QOS_CONSOLE_WAIT_MS 20
#endif
static int console_stalled;            /* the last byte found fd 1 unwritable */
static unsigned long console_dropped;  /* bytes dropped since writing last resumed */
/* The console's own notes go to stderr ONLY.  qos_console_putc runs inside
 * the app's console echo (fpr_logput holds fpr_con_lock around hal_putc), so
 * a note through qos_hostlog would call the app's sink -- fpr_logput again,
 * on the same thread -- which spins for ever on the lock it already holds.
 * That was the "panic last words" hang: a panic echoed, the console
 * stalled or recovered mid-line, and the panic record was never written
 * (docs/2026-10-03-PREEXISTING-FAILURES.md).  The header's law applies:
 * nothing that runs under the app's locks may reach the sink. */
static void console_note(const char *fmt, unsigned long v) {
  fprintf(stderr, fmt, v);
  fputc('\n', stderr);
}
void qos_console_putc(char c) {
  struct pollfd p = {1, POLLOUT, 0};
  int r = poll(&p, 1, console_stalled ? 0 : QOS_CONSOLE_WAIT_MS);
  if (r > 0 && (p.revents & POLLOUT)) {
    if (console_stalled) {
      console_stalled = 0;
      console_note("[qosp] console writable again: %lu byte(s) dropped while it was not", console_dropped);
      console_dropped = 0;
    }
    ssize_t w = write(1, &c, 1);
    (void)w; /* console loss is not an image error */
    return;
  }
  if (!console_stalled) console_note("[qosp] console not writable within %lu ms: dropping output until it is", (unsigned long)QOS_CONSOLE_WAIT_MS);
  console_stalled = 1;
  console_dropped++;
}

void qos_hostlog_set_sink(void (*sink)(const char *line, uint64_t n)) {
  pthread_mutex_lock(&hl_mu);
  g_sink = sink;
  uint64_t have = pend_seq < PEND_N ? pend_seq : PEND_N;
  uint64_t first = pend_seq - have;
  pthread_mutex_unlock(&hl_mu);
  if (!sink) return;
  /* replay outside the mutex: the sink takes the app's own locks */
  for (uint64_t i = first; i < first + have; i++) {
    const char *l = pend[i % PEND_N];
    sink(l, (uint64_t)strlen(l));
  }
}
