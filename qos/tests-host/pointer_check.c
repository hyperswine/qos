#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdarg.h>
#include "../../hal/unix/hostlog.h"
void qos_hostlog(const char *format, ...) { (void)format; }
#include "../../hal/unix/mice_raw.c"
static void ev(int fd, unsigned type, unsigned code, int value) {
  struct input_event event = {0}; event.type = type; event.code = code; event.value = value;
  assert(write(fd, &event, sizeof event) == sizeof event);
}
static void expect(int kind, int a, int b) {
  int64_t k, x, y; assert(qos_mice_poll(&k, &x, &y));
  assert(k == kind && x == a && y == b);
}
static void raw(pointer_source *p, unsigned type, unsigned code, int value) {
  struct input_event event = {0}; event.type = type; event.code = code; event.value = value; pointer_event(p, &event);
}
int main(void) {
  char path[] = "/tmp/qos-pointer-check.XXXXXX"; int fd = mkstemp(path); assert(fd >= 0);
  setenv("FPR_EVDEV", "/dev/null", 1); setenv("FPR_POINTER_EVDEV", path, 1);
  struct input_event partial = {0}; partial.type = EV_REL; partial.code = REL_X; partial.value = 8;
  assert(write(fd, &partial, 7) == 7);
  int64_t k, a, b; assert(!qos_mice_poll(&k, &a, &b));
  assert(pointer_sources[0].used == 7);
  assert(write(fd, ((unsigned char *)&partial) + 7, sizeof partial - 7) == sizeof partial - 7);
  ev(fd, EV_REL, REL_Y, 3); ev(fd, EV_KEY, BTN_LEFT, 1); ev(fd, EV_REL, REL_WHEEL, 1); ev(fd, EV_SYN, SYN_REPORT, 0);
  expect(2, 8, -3); expect(3, 1, 0); expect(6, 10, 0);
  ev(fd, EV_ABS, ABS_X, 65535); ev(fd, EV_ABS, ABS_Y, 32767); ev(fd, EV_SYN, SYN_REPORT, 0);
  expect(9, 65535, 32767);
  ev(fd, EV_SYN, SYN_DROPPED, 0); ev(fd, EV_KEY, BTN_LEFT, 1); ev(fd, EV_SYN, SYN_REPORT, 0);
  expect(10, 0, 0); assert(!qos_mice_poll(&k, &a, &b));
  assert(!pointer_sources[0].buttons && !pointer_sources[0].desynced);
  pointer_source p = {0}; p.xmax = 1000; p.ymax = 2000;
  pointer_qr = pointer_qw = 0;
  raw(&p, EV_KEY, BTN_TOUCH, 1); raw(&p, EV_ABS, ABS_MT_SLOT, 1);
  raw(&p, EV_ABS, ABS_MT_TRACKING_ID, 10); raw(&p, EV_ABS, ABS_MT_POSITION_X, 500);
  raw(&p, EV_ABS, ABS_MT_POSITION_Y, 1000); raw(&p, EV_SYN, SYN_REPORT, 0);
  assert(!pointer_qw); /* A secondary contact must never tap the primary origin. */
  raw(&p, EV_ABS, ABS_MT_SLOT, 0); raw(&p, EV_ABS, ABS_MT_TRACKING_ID, 11);
  raw(&p, EV_ABS, ABS_MT_POSITION_X, 500); raw(&p, EV_ABS, ABS_MT_POSITION_Y, 1000); raw(&p, EV_SYN, SYN_REPORT, 0);
  assert(pointer_qw == 2 && pointer_queue[0].kind == 9 && pointer_queue[0].a == 32767 && pointer_queue[0].b == 32767);
  assert(pointer_queue[1].kind == 3 && pointer_queue[1].a == 1);
  close(fd); unlink(path); puts("pointer: partial records, report order, wheel, touch, cancellation HOLDS"); return 0;
}
