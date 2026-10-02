/* Exercise the production console writer against a real, blocking, full
 * pipe. stderr stays drained so diagnostics are observable independently. */
#include "hostlog.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>
static double now(void) {
  struct timespec ts; assert(clock_gettime(CLOCK_MONOTONIC, &ts) == 0);
  return ts.tv_sec + ts.tv_nsec / 1e9;
}
int main(void) {
  int p[2]; assert(pipe(p) == 0);
  int saved = dup(1); assert(saved >= 0);
  int flags = fcntl(p[1], F_GETFL); assert(flags >= 0);
  assert(fcntl(p[1], F_SETFL, flags | O_NONBLOCK) == 0);
  char buf[4096] = {0};
  while (write(p[1], buf, sizeof buf) > 0) {}
  assert(errno == EAGAIN);
  while (write(p[1], buf, 1) > 0) {}
  assert(errno == EAGAIN);
  assert(fcntl(p[1], F_SETFL, flags) == 0);
  assert(dup2(p[1], 1) == 1);
  int before = fcntl(1, F_GETFL);
  double t0 = now();
  for (int i = 0; i < 5000; i++) qos_console_putc('x');
  double elapsed = now() - t0;
  assert(elapsed < .5); /* 5,000 bounded waits would be 100 seconds */
  assert(fcntl(1, F_GETFL) == before && !(before & O_NONBLOCK));
  assert(fcntl(p[0], F_SETFL, O_NONBLOCK) == 0);
  while (read(p[0], buf, sizeof buf) > 0) {}
  assert(errno == EAGAIN);
  qos_console_putc('R');
  assert(read(p[0], buf, sizeof buf) == 1 && buf[0] == 'R');
  /* A second stall must arm one new wait, then report its own drop count. */
  assert(fcntl(p[1], F_SETFL, flags | O_NONBLOCK) == 0);
  while (write(p[1], buf, 1) > 0) {}
  assert(errno == EAGAIN);
  assert(fcntl(p[1], F_SETFL, flags) == 0);
  qos_console_putc('y');
  while (read(p[0], buf, sizeof buf) > 0) {}
  qos_console_putc('S');
  assert(read(p[0], buf, sizeof buf) == 1 && buf[0] == 'S');
  assert(dup2(saved, 1) == 1);
  close(saved); close(p[0]); close(p[1]);
  printf("consolefull: blocking flags preserved, 5000 drops in %.3fs, resume and restall HOLDS\n", elapsed);
}
