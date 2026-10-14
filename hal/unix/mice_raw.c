/* mice_raw.c (unix) -- evdev mouse/wheel/primary-contact touch, with
 * the legacy PS/2 aggregate fallback described below.
 *
 * The fallback MOUSE tier: /dev/input/mice, the kernel's
 * PS/2-style aggregate of every pointer plugged in.  It needs no window
 * system and no per-device discovery, so it is what a bare Linux console
 * (the Pi target) has; it is simply absent under containers and on hosts
 * that are not Linux, and then this tier reports nothing, once, in the log.
 *
 * It used to live inside gfx.c's desktop-GL poll, so an image without the
 * GL stack had no mouse at all.  Input is its own capability: both the GL
 * tier and the headless tier (tty_raw.c) read pointers through here.
 *
 *   kind 2  (2, dx, dy)      relative motion, PS/2 sense: +y is UP
 *   kind 3  (3, buttons, 0)  the button mask after a change
 *                            (1 left, 2 right, 4 middle)
 *
 * A packet can carry motion AND a button change; the change used to be
 * dropped whenever the pointer was also moving.  Here the motion is
 * reported first and the change on the next poll.
 */
#include "evdev_raw.h"
#include "hostlog.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

/* Evdev pointers report facts at SYN_REPORT boundaries. The FP-RISC input
 * adapter owns viewport mapping, capture, wheel pacing and activation. */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/stat.h>
#ifdef __linux__
#include <linux/input.h>
#include <sys/ioctl.h>
#else
#include <sys/time.h>
struct input_event { struct timeval time; unsigned short type, code; int32_t value; };
#define EV_SYN 0
#define EV_KEY 1
#define EV_REL 2
#define EV_ABS 3
#define SYN_REPORT 0
#define SYN_DROPPED 3
#define REL_X 0
#define REL_Y 1
#define REL_HWHEEL 6
#define REL_WHEEL 8
#define ABS_X 0
#define ABS_Y 1
#define ABS_MT_SLOT 0x2f
#define ABS_MT_POSITION_X 0x35
#define ABS_MT_POSITION_Y 0x36
#define ABS_MT_TRACKING_ID 0x39
#define BTN_LEFT 0x110
#define BTN_RIGHT 0x111
#define BTN_MIDDLE 0x112
#define BTN_TOUCH 0x14a
#endif

typedef struct {
  int fd, slot, buttons, reported, abs_dirty, x, y, desynced, mt;
  int xmin, xmax, ymin, ymax;
  int64_t dx, dy, wheel, hwheel;
  unsigned char bytes[sizeof(struct input_event)];
  size_t used;
} pointer_source;
static pointer_source pointer_sources[32];
static int pointer_count, pointer_tried, pointer_explicit;
static struct { int64_t kind, a, b; } pointer_queue[5];
static unsigned pointer_qr, pointer_qw;
static void pointer_push(int64_t kind, int64_t a, int64_t b) {
  /* One SYN report emits at most four facts; the queue is drained before
   * another report is read. SYN_DROPPED emits only cancellation. */
  pointer_queue[pointer_qw].kind = kind;
  pointer_queue[pointer_qw].a = a; pointer_queue[pointer_qw].b = b;
  pointer_qw++;
}
static int64_t pointer_normalize(int value, int low, int high) {
  if (high <= low) return 0;
  int64_t v = value; if (v < low) v = low; if (v > high) v = high;
  return (v - low) * 65535 / ((int64_t)high - low);
}
#ifdef __linux__
static int pointer_bit(const unsigned long *bits, unsigned n) {
  return (bits[n / (8 * sizeof(long))] >> (n % (8 * sizeof(long)))) & 1;
}
static int pointer_device(int fd) {
  unsigned long rel[(REL_MAX + 1) / (8 * sizeof(long)) + 1] = {0};
  unsigned long abs[(ABS_MAX + 1) / (8 * sizeof(long)) + 1] = {0};
  unsigned long keys[(KEY_MAX + 1) / (8 * sizeof(long)) + 1] = {0};
  int touch = ioctl(fd, EVIOCGBIT(EV_KEY, sizeof keys), keys) >= 0 &&
    (pointer_bit(keys, BTN_TOUCH) || pointer_bit(keys, BTN_TOOL_FINGER));
  if (ioctl(fd, EVIOCGBIT(EV_REL, sizeof rel), rel) >= 0 && pointer_bit(rel, REL_X) && pointer_bit(rel, REL_Y)) return 1;
  if (ioctl(fd, EVIOCGBIT(EV_ABS, sizeof abs), abs) >= 0 &&
      ((touch && pointer_bit(abs, ABS_X) && pointer_bit(abs, ABS_Y)) ||
       (pointer_bit(abs, ABS_MT_POSITION_X) && pointer_bit(abs, ABS_MT_POSITION_Y)))) return 1;
  return 0;
}
#endif
static void pointer_add(int fd, const char *path) {
  pointer_source *p = &pointer_sources[pointer_count++];
  memset(p, 0, sizeof *p); p->fd = fd; p->xmax = p->ymax = 65535;
#ifdef __linux__
  struct input_absinfo x, y;
  if ((ioctl(fd, EVIOCGABS(ABS_X), &x) >= 0 && ioctl(fd, EVIOCGABS(ABS_Y), &y) >= 0) ||
      (ioctl(fd, EVIOCGABS(ABS_MT_POSITION_X), &x) >= 0 && ioctl(fd, EVIOCGABS(ABS_MT_POSITION_Y), &y) >= 0)) {
    p->xmin = x.minimum; p->xmax = x.maximum; p->ymin = y.minimum; p->ymax = y.maximum;
  }
#endif
  qos_hostlog("[input] pointer: %s", path);
}
static void pointer_open(void) {
  if (pointer_tried) return;
  pointer_tried = 1;
  const char *path = getenv("FPR_POINTER_EVDEV");
  if (path && *path) {
    pointer_explicit = 1;
    int fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd >= 0) pointer_add(fd, path);
    else qos_hostlog("[input] pointer %s: %s", path, strerror(errno));
    return;
  }
  /* An explicit keyboard replay must not pick up live mouse/touch input. */
  const char *keyboard = getenv("FPR_EVDEV");
  if (keyboard && *keyboard && strcmp(keyboard, "auto")) { pointer_explicit = 1; return; }
#ifdef __linux__
  for (int i = 0; i < 32; i++) {
    char name[32]; snprintf(name, sizeof name, "/dev/input/event%d", i);
    int fd = open(name, O_RDONLY | O_NONBLOCK);
    if (fd >= 0) { if (pointer_device(fd)) pointer_add(fd, name); else close(fd); }
  }
#endif
}
static void pointer_event(pointer_source *p, const struct input_event *e) {
  if (p->desynced) {
    if (e->type == EV_SYN && e->code == SYN_REPORT) p->desynced = 0;
    return;
  }
  if (e->type == EV_SYN && e->code == SYN_DROPPED) {
    p->dx = p->dy = p->wheel = p->hwheel = 0;
    p->buttons = p->reported = p->abs_dirty = p->slot = 0; p->desynced = 1;
    pointer_push(10, 0, 0); return;
  }
  if (e->type == EV_SYN && e->code == SYN_REPORT) {
    if (p->dx || p->dy) pointer_push(2, p->dx, -p->dy);
    if (p->abs_dirty) pointer_push(9, pointer_normalize(p->x, p->xmin, p->xmax), pointer_normalize(p->y, p->ymin, p->ymax));
    if (p->buttons != p->reported) { pointer_push(3, p->buttons, 0); p->reported = p->buttons; }
    if (p->wheel || p->hwheel) pointer_push(6, p->wheel * 10, p->hwheel * 10);
    p->dx = p->dy = p->wheel = p->hwheel = 0; p->abs_dirty = 0; return;
  }
  if (e->type == EV_REL) {
    if (e->code == REL_X) p->dx += e->value;
    if (e->code == REL_Y) p->dy += e->value;
    if (e->code == REL_WHEEL) p->wheel += e->value;
    if (e->code == REL_HWHEEL) p->hwheel += e->value;
  }
  if (e->type == EV_ABS) {
    if (e->code == ABS_MT_SLOT || e->code == ABS_MT_TRACKING_ID) {
      if (!p->mt) p->buttons &= ~1;
      p->mt = 1;
    }
    if (e->code == ABS_MT_SLOT) p->slot = e->value;
    if (e->code == ABS_X || (p->slot == 0 && e->code == ABS_MT_POSITION_X)) { p->x = e->value; p->abs_dirty = 1; }
    if (e->code == ABS_Y || (p->slot == 0 && e->code == ABS_MT_POSITION_Y)) { p->y = e->value; p->abs_dirty = 1; }
    if (p->slot == 0 && e->code == ABS_MT_TRACKING_ID) { if (e->value < 0) p->buttons &= ~1; else p->buttons |= 1; }
  }
  if (e->type == EV_KEY) {
    int bit = e->code == BTN_LEFT || e->code == BTN_TOUCH ? 1 : e->code == BTN_RIGHT ? 2 : e->code == BTN_MIDDLE ? 4 : 0;
    if (p->mt && e->code == BTN_TOUCH) bit = 0;
    if (e->value) p->buttons |= bit; else p->buttons &= ~bit;
  }
}
static int pointer_poll(int64_t *kind, int64_t *a, int64_t *c) {
  pointer_open();
  if (pointer_qr == pointer_qw) {
    pointer_qr = pointer_qw = 0;
    for (int i = 0; i < pointer_count && !pointer_qw; i++) {
      pointer_source *p = &pointer_sources[i]; if (p->fd < 0) continue;
      for (int records = 0; records < 64 && !pointer_qw; records++) {
        ssize_t n = read(p->fd, p->bytes + p->used, sizeof(struct input_event) - p->used);
        if (n <= 0) {
          if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
            close(p->fd); p->fd = -1; pointer_push(10, 0, 0);
          }
          break;
        }
        p->used += (size_t)n;
        if (p->used == sizeof(struct input_event)) {
          struct input_event event; memcpy(&event, p->bytes, sizeof event); p->used = 0; pointer_event(p, &event);
        }
      }
    }
  }
  if (pointer_qr == pointer_qw) return 0;
  *kind = pointer_queue[pointer_qr].kind; *a = pointer_queue[pointer_qr].a; *c = pointer_queue[pointer_qr].b;
  pointer_qr++; return 1;
}

static int mice_fd = -2;   /* -2 untried, -1 unavailable */
static int buttons;        /* the mask last REPORTED */
static int pending = -1;   /* a mask still to report, or -1 */

int qos_mice_poll(int64_t *kind, int64_t *a, int64_t *c) {
  if (pointer_poll(kind, a, c)) return 1;
  if (pointer_count || pointer_explicit) return 0;
  if (pending >= 0) {
    *kind = 3; *a = pending; *c = 0;
    buttons = pending;
    pending = -1;
    return 1;
  }
  if (mice_fd == -2) {
#ifdef __linux__
    mice_fd = open("/dev/input/mice", O_RDONLY | O_NONBLOCK);
    if (mice_fd < 0)
      qos_hostlog("[input] no mouse at /dev/input/mice: %s%s", strerror(errno),
                  errno == EACCES ? " (add the user to the `input` group)" : "");
    else
      qos_hostlog("[input] mouse: /dev/input/mice");
#else
    mice_fd = -1;
#endif
  }
  if (mice_fd < 0) return 0;
  unsigned char pkt[3];
  while (read(mice_fd, pkt, 3) == 3) {
    int now = pkt[0] & 7;
    int dx = (signed char)pkt[1], dy = (signed char)pkt[2];
    if (dx || dy) {
      if (now != buttons) pending = now;
      *kind = 2; *a = dx; *c = dy;
      return 1;
    }
    if (now != buttons) {
      buttons = now;
      *kind = 3; *a = now; *c = 0;
      return 1;
    }
    /* neither moved nor changed: the device's keep-alive; read on */
  }
  return 0;
}
