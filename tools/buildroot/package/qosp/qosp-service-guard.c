/* An advisory lock across exec. All lifecycle policy remains in the scripts. */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#define _DEFAULT_SOURCE 1
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/file.h>
#include <time.h>
#include <unistd.h>

static long long millis(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts)) return -1;
  return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

int main(int argc, char **argv) {
  if (argc < 3) { fprintf(stderr, "usage: qosp-service-guard lock command [args...]\n"); return 2; }
  int fd = open(argv[1], O_CREAT | O_RDWR, 0600);
  if (fd < 0) { perror("qosp: control lock"); return 1; }
  long long start = millis();
  if (start < 0) { perror("qosp: monotonic clock"); return 1; }
  while (flock(fd, LOCK_EX | LOCK_NB)) {
    if (errno != EWOULDBLOCK && errno != EAGAIN && errno != EINTR) { perror("qosp: control lock"); return 1; }
    long long now = millis();
    if (now < 0 || now - start >= 5000) { fprintf(stderr, "qosp: another lifecycle command is busy\n"); return 1; }
    struct timespec pause = {0, 10000000};
    nanosleep(&pause, NULL);
  }
  /* The wrapper closes 9 before its detached child and startup wait. */
  if (fd != 9) {
    if (dup2(fd, 9) < 0) { perror("qosp: control descriptor"); return 1; }
    close(fd);
  }
  if (setenv("QOSP_SERVICE_GUARDED", "1", 1)) { perror("qosp: control environment"); return 1; }
  execvp(argv[2], argv + 2);
  perror("qosp: lifecycle command");
  return 1;
}
