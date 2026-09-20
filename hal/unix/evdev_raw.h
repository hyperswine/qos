/* evdev_raw.h -- the evdev keyboard tier (net_raw.h's input sibling).
 *
 * Reads Linux `struct input_event` records -- the evdev wire format,
 * what libevdev parses -- from the fd named by FPR_EVDEV.  Raw evdev
 * rather than libevdev-the-library, per the input-stack decision: no
 * layout/character translation is wanted (control input only), and no
 * dynamic dependency lands in static images.  The point of speaking
 * the real wire format is that ONE reader serves every source:
 *
 *   FPR_EVDEV=/dev/input/event3   a real keyboard (Pi console target)
 *   FPR_EVDEV=/tmp/kbd.fifo       a live simulated device (tools/kbdsim.py)
 *   FPR_EVDEV=script.evd          a pre-baked deterministic event file
 *   FPR_EVDEV=auto                every real keyboard, discovered (what a
 *                                 windowed host does with it unset; on a
 *                                 headless host it has to be asked for,
 *                                 because there the terminal is the default)
 *
 * EV_KEY events surface as input kind 4: (4, keycode, value) with
 * value 0 = release, 1 = press, 2 = autorepeat -- additive next to the
 * existing kinds (1 stdin byte, 2 mouse move, 3 mouse buttons), so
 * nothing downstream changes.  EV_SYN/EV_MSC are skipped here; an app
 * that wants SYN-framed batching can get it later as another kind. */
#ifndef QOS_EVDEV_RAW_H
#define QOS_EVDEV_RAW_H

#include <stdint.h>

/* 1 = event delivered (kind=4, a=keycode, c=value); 0 = none pending */
int qos_evdev_poll(int64_t *kind, int64_t *a, int64_t *c);
/* a windowing host (GLFW under FPR_DESKTOP_GL) feeds key
 * events translated to EVDEV CODES through here; they pass the same
 * modifier machine as device records.  Returns 0 (and drops the
 * event) when FPR_EVDEV names an explicit source -- a live window
 * must not contaminate a replay. */
int qos_evdev_inject(unsigned code, int value);
/* how many sources are open (opens them on first use): 0 means there is no
 * keyboard to read and the caller should fall back to the terminal */
int qos_evdev_sources(void);

/* the mouse tier (mice_raw.c): 1 = event delivered -- (2, dx, dy) relative
 * motion with +y UP, or (3, buttons, 0) the mask after a change */
int qos_mice_poll(int64_t *kind, int64_t *a, int64_t *c);

#endif
