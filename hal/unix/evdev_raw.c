/* evdev_raw.c -- see evdev_raw.h.  The reading discipline handles all
 * three source shapes with one code path: nonblocking reads into an
 * accumulation buffer (a FIFO or a slow real device may deliver a
 * partial record; a pre-baked file delivers many at once), records
 * consumed one per poll so an MVU tick sees at most one event. */
#include "evdev_raw.h"
#include "hostlog.h"

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#ifdef __linux__
#include <linux/input.h>
#else
/* Not Linux: no evdev bus, but the RECORD FORMAT still works -- the fd
 * FPR_EVDEV names is a tools/kbdsim.py FIFO or a pre-baked event file
 * carrying these same fixed-layout records.  Defining the wire struct
 * locally makes the simulated-keyboard/replay tier portable (macOS
 * included); only the /dev/input/eventN real-device shape is Linux. */
#include <sys/time.h>
struct input_event {
  struct timeval time;
  unsigned short type;
  unsigned short code;
  unsigned int value;
};
#define EV_KEY 0x01
/* the keycodes the decoder itself names (the WIRE speaks these
 * numbers on every platform; only /dev/input is Linux) */
#define KEY_Q 16
#define KEY_P 25
#define KEY_A 30
#define KEY_L 38
#define KEY_Z 44
#define KEY_M 50
#define KEY_LEFTSHIFT 42
#define KEY_RIGHTSHIFT 54
#define KEY_LEFTCTRL 29
#define KEY_RIGHTCTRL 97
#define KEY_LEFTALT 56
#define KEY_RIGHTALT 100
#define KEY_CAPSLOCK 58
#endif

#include <stdio.h>

/* Up to MAXKBD simultaneous sources.  FPR_EVDEV names ONE explicit
 * source (device node, kbdsim FIFO, or a pre-baked file) and, for
 * replay determinism, DISABLES discovery.  With it unset, Linux hosts
 * AUTO-DISCOVER real keyboards: scan /dev/input/event0..31 and keep
 * every node whose EV_KEY capability bitmap covers the letter block
 * (KEY_Q..KEY_M, 16..50) -- the same classification the qos-shell shim
 * used; mice/buttons/lid switches all fail it.  Every attempt is
 * logged once to stderr, because "plugged a keyboard in and nothing
 * happened" is otherwise undiagnosable: the usual cause is the process
 * not being in the `input` group (EACCES), and the log says so. */
#define MAXKBD 8
static int ev_fds[MAXKBD];
static int ev_nfds;
static int ev_tried;
static unsigned char buf[sizeof(struct input_event) * 32];
static size_t buflen;
static int shift_held, ctrl_held, alt_held, caps_on;

/* ---- synthetic injection --------------------------------
 * A windowing host (gfx.c under FPR_DESKTOP_GL) translates its own key
 * events to EVDEV CODES and injects them here, so the modifier state
 * machine below -- shift/ctrl/alt biasing, the capslock lock semantics
 * -- stays the ONE place that owns keyboard meaning, and the app-side
 * keymap (appkit keyChar) works unchanged.  FPR_EVDEV set = injection
 * DISABLED: an explicit source is the replay-determinism contract, and
 * a live window must not be able to contaminate a replay. */
#define INJ_CAP 128
static struct { unsigned short code; int value; } inj_ring[INJ_CAP];
static unsigned inj_r, inj_w;
static int inj_enabled = -1;

/* the EXPLICIT source FPR_EVDEV names, or 0: unset and `auto` both mean
 * "discover" */
static const char *explicit_source(void) {
  const char *path = getenv("FPR_EVDEV");
  return (path && *path && strcmp(path, "auto")) ? path : 0;
}

int qos_evdev_inject(unsigned code, int value) {
  if (inj_enabled < 0) inj_enabled = explicit_source() ? 0 : 1;
  if (!inj_enabled) return 0;
  unsigned next = (inj_w + 1) % INJ_CAP;
  if (next == inj_r) inj_r = (inj_r + 1) % INJ_CAP; /* oldest drops */
  inj_ring[inj_w].code = (unsigned short)code;
  inj_ring[inj_w].value = value;
  inj_w = next;
  return 1;
}

/* the letter block, in keycode order: q..p, a..l, z..m */
static int is_letter_code(unsigned code) {
  return (code >= KEY_Q && code <= KEY_P) || (code >= KEY_A && code <= KEY_L) ||
         (code >= KEY_Z && code <= KEY_M);
}

#ifdef __linux__
static int is_keyboard(int fd) {
  unsigned long evbits = 0;
  unsigned long keybits[(KEY_MAX + 1) / (8 * sizeof(long)) + 1];
  if (ioctl(fd, EVIOCGBIT(0, sizeof evbits), &evbits) < 0) return 0;
  if (!(evbits & (1ul << EV_KEY))) return 0;
  memset(keybits, 0, sizeof keybits);
  if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof keybits), keybits) < 0) return 0;
  for (int code = KEY_Q; code <= KEY_M; code++)  /* 16..50: the letters */
    if (!(keybits[code / (8 * sizeof(long))] &
          (1ul << (code % (8 * sizeof(long))))))
      return 0;
  return 1;
}
#endif

static void ev_open(void) {
  if (ev_tried) return;
  ev_tried = 1;
  const char *path = explicit_source();
  if (path) {
    /* O_NONBLOCK also makes a writer-less FIFO open succeed immediately */
    int fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd >= 0) {
      ev_fds[ev_nfds++] = fd;
      qos_hostlog("[input] FPR_EVDEV source: %s", path);
    } else
      qos_hostlog("[input] FPR_EVDEV %s: %s", path, strerror(errno));
    return; /* explicit source = no discovery (replay determinism) */
  }
#ifdef __linux__
  int denied = 0;
  for (int i = 0; i < 32 && ev_nfds < MAXKBD; i++) {
    char p[32];
    snprintf(p, sizeof p, "/dev/input/event%d", i);
    int fd = open(p, O_RDONLY | O_NONBLOCK);
    if (fd < 0) {
      if (errno == EACCES) { denied++; qos_hostlog("[input] %s: permission denied", p); }
      continue;
    }
    if (is_keyboard(fd)) {
      char name[64] = "?";
      ioctl(fd, EVIOCGNAME(sizeof name), name);
      qos_hostlog("[input] keyboard: %s (%s)", p, name);
      ev_fds[ev_nfds++] = fd;
    } else
      close(fd);
  }
  if (!ev_nfds)
    qos_hostlog("%s", denied
                ? "[input] no readable keyboards (add the user to the `input` group)"
                : "[input] no keyboards discovered (evdev falls back to stdin)");
#endif
}

int qos_evdev_sources(void) {
  ev_open();
  return ev_nfds;
}

/* the modifier machine: ONE decoder for device records and injected
 * synthetics alike.  Returns 1 with a (biased) keypress, 0 for events
 * that are state, not keys (modifiers, capslock). */
static int decode_key(unsigned short code, int value,
                      int64_t *kind, int64_t *a, int64_t *c) {
  if (code == KEY_LEFTSHIFT || code == KEY_RIGHTSHIFT) {
    if (value != 2) shift_held = value ? 1 : 0;
    return 0; /* the modifier itself is not a keypress */
  }
  if (code == KEY_LEFTCTRL || code == KEY_RIGHTCTRL) {
    if (value != 2) ctrl_held = value ? 1 : 0;
    return 0;
  }
  if (code == KEY_LEFTALT || code == KEY_RIGHTALT) {
    if (value != 2) alt_held = value ? 1 : 0;
    return 0;
  }
  if (code == KEY_CAPSLOCK) {
    if (value == 1) caps_on = !caps_on;
    return 0;
  }
  int bias = 0;
  if (shift_held) bias += 1000;
  if (ctrl_held) bias += 4000;
  if (alt_held) bias += 8000;
  if (caps_on && !shift_held && is_letter_code(code)) bias += 1000;
  if (caps_on && shift_held && is_letter_code(code)) bias -= 1000;
  *kind = 4;
  *a = code + bias;
  *c = value;
  return 1;
}

int qos_evdev_poll(int64_t *kind, int64_t *a, int64_t *c) {
  /* injected synthetics first (empty unless a windowing host feeds
   * them; disabled outright under FPR_EVDEV -- see qos_evdev_inject) */
  while (inj_r != inj_w) {
    unsigned short code = inj_ring[inj_r].code;
    int value = inj_ring[inj_r].value;
    inj_r = (inj_r + 1) % INJ_CAP;
    if (decode_key(code, value, kind, a, c)) return 1;
  }
  ev_open();
  if (!ev_nfds) return 0;
  /* top up the buffer from every source (partial trailing records stay
   * for next poll).  Interleaving across sources at record granularity
   * is fine: each read appends whole-record multiples in practice, and
   * the parser below is byte-accurate regardless. */
  for (int i = 0; i < ev_nfds && buflen < sizeof buf; i++) {
    ssize_t n = read(ev_fds[i], buf + buflen, sizeof buf - buflen);
    if (n > 0) buflen += (size_t)n;
    /* n == 0: EOF -- a drained pre-baked file or a closed FIFO writer.
     * Keep the fd: a FIFO can gain a new writer; a file stays drained. */
  }
  /* consume whole records until an EV_KEY surfaces (one per poll) */
  while (buflen >= sizeof(struct input_event)) {
    struct input_event ev;
    memcpy(&ev, buf, sizeof ev);
    buflen -= sizeof ev;
    memmove(buf, buf + sizeof ev, buflen);
    if (ev.type == EV_KEY) {
      static int first = 1;
      if (first) {
        first = 0;
        qos_hostlog("[input] first key event: code %u value %d",
                (unsigned)ev.code, (int)ev.value);
      }
      /* MODIFIER STATE lives in decode_key, the one decoder every
       * source -- device records and injected synthetics alike --
       * passes through (biasing rationale documented there). */
      if (decode_key(ev.code, (int)ev.value, kind, a, c)) return 1;
      continue;
    }
    /* EV_SYN / EV_MSC / EV_LED ...: framing + metadata, skipped here */
  }
  return 0;
}
