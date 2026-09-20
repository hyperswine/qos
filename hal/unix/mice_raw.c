/* mice_raw.c (unix) -- the MOUSE tier: /dev/input/mice, the kernel's
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

static int mice_fd = -2;   /* -2 untried, -1 unavailable */
static int buttons;        /* the mask last REPORTED */
static int pending = -1;   /* a mask still to report, or -1 */

int qos_mice_poll(int64_t *kind, int64_t *a, int64_t *c) {
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
