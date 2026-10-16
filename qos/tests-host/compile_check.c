/* compile_check.c -- the worker-backed compile bridge (portable/compile.c,
 * ABI v21) against a fake daemon (compile_check.py): a reply far past the
 * old 256 KiB channel buffer arrives whole, a missing daemon is -2, a
 * daemon that never answers is -3, and a request abandoned by its caller
 * is freed by the worker while a later one is still answered.  Built with
 * the sanitizers by compile-check.sh. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

void *qosp_compile_submit(const char *pay, uint64_t plen);
int qosp_compile_done(void *job);
int64_t qosp_compile_reply(void *job, const char **bytes);
void qosp_compile_release(void *job);

static int64_t answer(const char *req, const char **bytes, void **job) {
  *job = qosp_compile_submit(req, strlen(req));
  if (!*job) return -100;
  for (int i = 0; i < 30000 && !qosp_compile_done(*job); i++) usleep(1000);
  return qosp_compile_reply(*job, bytes);
}

int main(int argc, char **argv) {
  if (argc < 2) return 2;
  const char *b;
  void *j;
  if (!strcmp(argv[1], "big")) {
    int64_t r = answer("qos-portable\nmain = 1.", &b, &j);
    int whole = r == 3 + (1 << 20) && !memcmp(b, "ok\n", 3) && b[3] == 'x' && b[r - 1] == 'x';
    printf("big %lld %s\n", (long long)r, whole ? "whole" : "TORN");
    qosp_compile_release(j);
    return !whole;
  }
  if (!strcmp(argv[1], "none")) {
    int64_t r = answer("qos-portable\nmain = 1.", &b, &j);
    printf("none %lld\n", (long long)r);
    qosp_compile_release(j);
    return r != -2;
  }
  if (!strcmp(argv[1], "silent")) {
    int64_t r = answer("silent\nx", &b, &j);
    printf("silent %lld\n", (long long)r);
    qosp_compile_release(j);
    return r != -3;
  }
  if (!strcmp(argv[1], "abandon")) {
    void *slow = qosp_compile_submit("slow\nx", 6);
    qosp_compile_release(slow); /* the caller gives up at once */
    int64_t r = answer("qos-portable\nmain = 1.", &b, &j);
    printf("abandon %lld\n", (long long)r);
    qosp_compile_release(j);
    return r != 3 + (1 << 20);
  }
  return 2;
}
