#include <errno.h>
/* haltab.c -- the Initializer stage's product: the HAL table.
 *
 * The bootstrap design's stage-1 job on this "board": build the HAL as
 * in-memory C ABI functions wrapping the platform's actual operations,
 * delivered to the loaded program as one table pointer.  The board is
 * libc; the operations are the SAME raw tier posix.bin co-compiles
 * (runtime/posix/net_raw.c) -- one implementation, two dispatch
 * disciplines, which is the whole point of the split.
 *
 * Unmapped-register faults are honest and immediate, matching the
 * co-compiled HAL's fpr_cpanic behavior: the app named a capability
 * this table does not carry, and continuing would lie about it. */
#include "qos_abi.h"
#include "hostlog.h"
#include "net_raw.h"
#include "blk_raw.h"
#include "snd_raw.h"
#ifdef QOSP_GFX
#include "gfx_raw.h"
#else
/* input WITHOUT the GL stack: the tty/evdev tier (hal/unix/tty_raw.c
 * + evdev_raw.c, compiled with QOSP_HOST).  Input is its own
 * capability -- a terminal app should not need a window to read
 * keys. */
int qos_tty_poll(int64_t *kind, int64_t *a, int64_t *c);
int qos_evdev_poll(int64_t *kind, int64_t *a, int64_t *c);
#endif

#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

#ifndef QOSP_GFX
static int size_hook_state; /* 0 unchecked, 1 pending, 2 done */
static int64_t size_hook_c, size_hook_r;
static int t_input_poll(int64_t *kind, int64_t *a, int64_t *c) {
  *kind = 0; *a = 0; *c = 0;
  if (!size_hook_state) {
    const char *s = getenv("FPR_TTY_SIZE");
    size_hook_state = (s && sscanf(s, "%lld %lld", (long long *)&size_hook_c,
                                   (long long *)&size_hook_r) == 2) ? 1 : 2;
  }
  if (size_hook_state == 1) { /* one kind-5 before any key */
    size_hook_state = 2;
    *kind = 5; *a = size_hook_c; *c = size_hook_r;
    return 1;
  }
  if (getenv("FPR_EVDEV")) return qos_evdev_poll(kind, a, c);
  return qos_tty_poll(kind, a, c);
}
#endif

static void t_putc(char c) {
  ssize_t r = write(1, &c, 1);
  (void)r; /* console loss is not an image error */
}

static void t_poweroff(int code) { exit(code); }

static void t_wfi(void) { /* poll pace, posix hal.c's value */
  struct timespec ts = {0, 200 * 1000}, t0, t1;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  int r = nanosleep(&ts, 0);
  clock_gettime(CLOCK_MONOTONIC, &t1);
  long ms = (t1.tv_sec - t0.tv_sec) * 1000 + (t1.tv_nsec - t0.tv_nsec) / 1000000;
  if (r != 0 || ms > 50) qos_hostlog("qosp: wfi took %ld ms (r=%d errno=%d)", ms, r, errno);
}

static uint64_t t_mmio_read(uint64_t addr, uint32_t width) {
  (void)width;
  uint64_t out;
  if (qos_mmioraw_read(addr, &out) < 0) {
    qos_hostlog("qosp HAL: app read an unmapped register (0x%llx)",
                (unsigned long long)addr);
    exit(1);
  }
  return out;
}

static void t_mmio_write(uint64_t addr, uint64_t v, uint32_t width) {
  (void)width;
  if (qos_mmioraw_write(addr, v) < 0) {
    qos_hostlog("qosp HAL: app wrote an unmapped register (0x%llx)",
                (unsigned long long)addr);
    exit(1);
  }
}

static int64_t qosp_clock_now(void) { return (int64_t)time(NULL); }
/* the stack guard IS the posix HAL's (qosp is a posix FP-RISC program, so
 * fprisc/hal/posix/hal.c is linked here): one implementation, two callers */
void hal_stack_guard(void *lo, uint64_t size);
void hal_stack_unguard(void *lo, uint64_t size);
static void qosp_stack_guard(void *lo, uint64_t size) { hal_stack_guard(lo, size); }
static void qosp_stack_unguard(void *lo, uint64_t size) { hal_stack_unguard(lo, size); }
void *(*qosp_app_stack_query)(uint64_t *id, uint64_t *size); /* host.c's fault handler asks it */
static void qosp_set_stack_query(void *(*q)(uint64_t *, uint64_t *)) { qosp_app_stack_query = q; }

static qos_hal_t the_table = {
    .version = QOS_ABI_VERSION,
    .nharts = 1, /* main.c raises this (and installs start_hart) at boot */
    .putc = t_putc,
    .poweroff = t_poweroff,
    .wfi = t_wfi,
    .mmio_read = t_mmio_read,
    .mmio_write = t_mmio_write,
    .dev_lookup = qos_devraw_lookup,
    .net_poll = qos_netraw_poll,
    .net_read = qos_netraw_read,
    .net_write = qos_netraw_write,
    .net_close = qos_netraw_close,
#ifdef QOSP_GFX
    .gfx_init = gfx_init,
    .gfx_dims = gfx_dims,
    .gfx_render = gfx_render_scene,
    .gfx_save_ppm = gfx_save_ppm,
    .gfx_input_poll = gfx_input_poll,
#else
    /* input granted WITHOUT gfx: the tty/evdev tier above.  The other
     * gfx_* slots stay NULL -- the app-side shims report those
     * capabilities as missing, honestly and separately. */
    .gfx_input_poll = t_input_poll,
#endif
    /* v4: the unified log plane (hostlog.h) -- the app registers its
     * sev-3 ring writer here and every qos_hostlog line becomes
     * browsable as /logs/host, pending boot lines replayed in order */
    .set_log_sink = qos_hostlog_set_sink,
    /* v5: the disk tier -- qosp.disk as policy-free 4 KiB pages
     * (blk_raw.c); the record/file policy above it is FPRISC
     * (mods/qlog.fpr), the same module native runs over virtio-blk */
    .blk_pages = qos_blkraw_pages,
    .blk_read = qos_blkraw_read,
    .blk_write = qos_blkraw_write,
    /* v7: the sound tier (snd_raw.c) -- always present on qosp; the
     * host itself is silent, honestly and once in the log, without a
     * device or a dump */
    .snd_play = qos_snd_play,
#ifdef QOSP_GFX
    /* v8: program-carried meshes (gfx.c gfx_mesh_load) */
    .gfx_mesh_load = gfx_mesh_load,
#endif
    /* v9: the music channel */
    .snd_music = qos_snd_music,
#ifdef QOSP_GFX
    /* v10: the 2D layer over the scene */
    .gfx_render_ui = gfx_render_overlay,
#endif
    /* v11: the wall clock */
    .clock_now = qosp_clock_now,
    .stack_guard = qosp_stack_guard,
    .stack_unguard = qosp_stack_unguard,
    .set_stack_query = qosp_set_stack_query,
};

const qos_hal_t *qosp_hal_table(void) { return &the_table; }

/* multi-hart wiring (ABI v2): the resolved live count and the host's
 * thread-creation callback, both owned by main.c */
void qosp_hal_set_smp(uint64_t nharts,
                      int (*sh)(uint64_t, void (*)(uint64_t))) {
  the_table.nharts = nharts;
  the_table.start_hart = sh;
}
