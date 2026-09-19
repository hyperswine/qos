/* qos_abi.h -- the QOS Portable host <-> app ABI (docs/QOS-PORTABLE.md).
 *
 * Shared by runtime/portable (the qosp host, hosted C with libc) and
 * runtime/qosapp (the app-side runtime, freestanding).  This is the
 * bootstrap design's HAL contract realized on a host OS: "the HAL is a
 * table delivered as a C pointer, called like regular C functions" --
 * the app image contains NO libc and NO syscalls; every effect it can
 * have on the world goes through this table, and the table's entries
 * are the image's runtime capability surface (the link-time fpr_g_
 * import set remains the static one, exactly as on bare metal).
 *
 * Only fixed-width C ABI types cross the boundary: the host and the
 * app are separately linked images that happen to share an address
 * space, the same relationship System.qa has with a loaded process on
 * virt.  No V values cross it in v1 -- both sides build their own.
 */
#ifndef QOS_ABI_H
#define QOS_ABI_H

#include <stdint.h>

#define QOS_ABI_VERSION 12u

/* ---- the address plan (linux-x86-64) --------------------------------
 * The host is linked non-PIE (default 0x400000 text); the arena is a
 * fixed mmap well away from it.  The image SLOT is the arena's first
 * QOS_SLOT_SIZE bytes, reserved via buddy_reserve_range -- so unlike
 * build-process-app.sh there is no +wordsize header bias to extract
 * from a symbol table: the link address is a CONSTANT, and an app.qa
 * built today loads under any qosp built tomorrow.  Everything after
 * the image is the APP'S OWN arena (v12): the host hands it over in
 * the boot record and the app runs the buddy -- behind its memory
 * actor (docs/MEMORY.md) -- itself; the host allocates nothing there. */
/* 16 GiB everywhere but macOS, which reserves 0x180000000-0x7000000000 in
 * every process (the dyld shared region, then a no-access block): a hint
 * in there is never honoured, so the Darwin slot is 1 TiB.  App images for
 * macOS are freestanding ELF (no __APPLE__), so qos-app.mk passes the base. */
#ifndef QOS_ARENA_BASE
#ifdef __APPLE__
#define QOS_ARENA_BASE 0x10000000000ul
#else
#define QOS_ARENA_BASE 0x400000000ul
#endif
#endif
#ifndef QOS_ARENA_SIZE
#define QOS_ARENA_SIZE (256ul << 20) /* the host build sets ARENA_MB (qos/Makefile) */
#endif
#define QOS_SLOT_SIZE (16ul << 20) /* matches link-app.ld's SLOT LENGTH */
#define QOS_SLOT_BASE QOS_ARENA_BASE
/* the PLUGIN slot: a second, smaller fixed-address window inside the
 * arena for DYNAMICALLY LOADED .qa libraries -- images linked at this
 * base against the running shell image's symbol addresses (a
 * PROVIDE()-script of the shell's nm output), carrying only their own
 * generated code + module table.  Loaded via syscall tag 4, registered
 * with the module registry, called through Mod.find PAPs.  The app
 * runtime EXCLUDES this range from fpr_in_heap (plugin rodata is
 * immortal literal data, not slab-backed heap). */
#define QOS_PLUG_BASE (QOS_ARENA_BASE + (128ul << 20))
#define QOS_PLUG_SIZE (32ul << 20) /* 8 sub-slots of 4 MiB */
/* syscall channel tags (boot->syscall_fn): 2 kv-append, 3 kv-replay,
 * 4 load-plugin (payload = the .qa CONTAINER BYTES, read off the disk
 * by the app itself -- qlog over the blk tier; returns the module-
 * table address as the int64, or <0 with an error string in out),
 * 5 kv record index, 6 sleep (payload = decimal MICROSECONDS text;
 * the app-side Sys.sleepUs backend -- weak/strong linking cannot
 * cross the image boundary, so the sleep goes through the channel
 * every other host service already uses), 7 compile (payload =
 * "<profile>\n<source>"; the host bridges to the fpr compiler
 * server on its unix socket -- portable/compile.c + tools/fprd.py --
 * and out gets the framed "ok\n<asm>" / "err\n<msg>" reply) */
#define QOS_SYS_LOADQA 4
#define QOS_SYS_SLEEPUS 6
#define QOS_SYS_COMPILE 7

/* ---- the HAL table --------------------------------------------------
 * The entries mirror the obligations runtime/posix's co-compiled HAL
 * satisfies (hal.c, stubs.c/net.c), so the SAME FPRISC surface --
 * console via the uart register model, mtime via the clint model,
 * `device "name"` discovery, netPoll/netRead/netWrite/netClose --
 * works unchanged; only the dispatch is a table call instead of a
 * link-time bind.  Nullable tiers (gfx) are NULL when the host was
 * built without them; the app-side shim panics honestly on use,
 * matching stubs.c's missing-capability behavior. */
typedef struct {
  uint64_t version; /* QOS_ABI_VERSION */
  uint64_t nharts;  /* v2: the host's RESOLVED hart-thread count (env
                     * FPR_HARTS, else the online-CPU count, clamped);
                     * the app clamps again to its own compile-time
                     * FPR_NHARTS cap and reports the result via
                     * Sys.harts.  1 under a v1-shaped single-hart run. */

  /* console + machine */
  void (*putc)(char c);
  void (*poweroff)(int code); /* terminates the "machine" (the host) */
  void (*wfi)(void);          /* idle pacing for the app's hart loop */

  /* the register tier: uart/clint pseudo-bus, same addresses as the
   * posix HAL's model (runtime/portable/haltab.c holds the dispatch) */
  uint64_t (*mmio_read)(uint64_t addr, uint32_t width);
  void (*mmio_write)(uint64_t addr, uint64_t v, uint32_t width);

  /* device discovery by name: 1 + *base filled, or 0 = unknown (the
   * app-side shim turns 0 into the same honest panic virt/posix use) */
  int (*dev_lookup)(const char *name, uint64_t len, uint64_t *base);

  /* net: the posix contract verbatim (one connection, poll-driven).
   * poll: 0 no conn, 1 open, 2 open+rx.  read drains into dst, returns
   * bytes.  write is blocking-full, returns len.  close keeps listening. */
  /* v6: connection-addressed (multi-conn).  poll returns a connection
   * id (1..) with buffered rx, else 0; read/write/close take the id. */
  int64_t (*net_poll)(void);
  int64_t (*net_read)(int64_t id, char *dst, uint64_t cap);
  int64_t (*net_write)(int64_t id, const char *src, uint64_t len);
  int64_t (*net_close)(int64_t id);

  /* gfx (NULLABLE: NULL in a host built without GFX=1 -- the app-side
   * shim panics honestly on use, the missing-capability behavior).
   * gfx_render takes the scene VALUE as a uint64_t: the host walks it
   * read-only through the shared fpr.h layout -- valid because the two
   * images share one address space; results leave via out-params and
   * the APP builds its own V results with its own allocator. */
  void (*gfx_init)(int w, int h);
  int (*gfx_render)(uint64_t scene, int64_t *draws, int64_t *dyn_bytes);
  int (*gfx_save_ppm)(const char *path);
  int (*gfx_input_poll)(int64_t *kind, int64_t *a, int64_t *c);

  /* ---- v2 additions (appended: v1 offsets unchanged) ----------------
   * start_hart (NULLABLE: NULL = single-hart host): create one host
   * thread for app hart `idx` and call fn(idx) on it -- the posix
   * pthread_create dance done host-side, because the app is
   * freestanding and cannot make threads.  The host trampoline owns
   * the thread; it joins them all after the entry returns (every hart
   * loop exits through fpr_process_done, so the joins are prompt). */
  int (*start_hart)(uint64_t idx, void (*fn)(uint64_t idx));

  /* ---- v3 additions (appended: earlier offsets unchanged) -----------
   * gfx_dims: the FBO size gfx_init settled on -- the AUTO-RESOLUTION
   * answer when the app passed 0 0 and the host sized the frame to the
   * connected display's own mode.  NULL on GFX-less hosts. */
  void (*gfx_dims)(int *w, int *h);

  /* ---- v4 additions (appended: earlier offsets unchanged) -----------
   * set_log_sink: the UNIFIED LOG PLANE (hostlog.h).  The app hands
   * the host its ring writer (fpr_logput at sev 3 = host) and every
   * qos_hostlog line -- DRM probe results, evdev opens, plugin load
   * ranges, mprotect boundaries -- lands in the app's /logs/host ring
   * as well as stderr; lines from before registration replay in
   * order.  entry.c registers it right after the hart-0 world is up,
   * so an app's very first frame can already browse the host's boot
   * story. */
  void (*set_log_sink)(void (*sink)(const char *line, uint64_t n));

  /* ---- v5 additions (appended: earlier offsets unchanged) -----------
   * the disk tier: qosp.disk as an array of 4 KiB pages -- hal/virt/
   * blk.c's policy-free contract, table-dispatched (blk_raw.h).  ALL
   * record/log/file policy stays in FPRISC (mods/qlog.fpr): the SAME
   * module System.qa runs over virtio-blk on native runs here over a
   * host file, and tools/mkdisk.py seeds either.  blk_pages returns 0
   * when the backing file could not be opened -- the honest no-disk
   * state system.fpr already degrades on; read/write return -1 out of
   * range (the app-side shim panics, matching virt). */
  int64_t (*blk_pages)(void);
  int64_t (*blk_read)(uint64_t page, char *dst /* 4096 bytes */);
  int64_t (*blk_write)(uint64_t page, const char *src, uint64_t len);

  /* ---- v7 additions (appended: earlier offsets unchanged) -----------
   * the sound tier: one procedural voice per call (hal/unix/snd_raw.h:
   * wave, start/end Hz, ms, milli-volume, ms delay), mixed by the host.
   * NULL on a host without it; the app-side shim reports the missing
   * capability the same way gfx does. */
  int (*snd_play)(int64_t wave, int64_t f0, int64_t f1, int64_t ms, int64_t vol, int64_t delay);

  /* ---- v8 additions (appended: earlier offsets unchanged) -----------
   * registered meshes: the program carries its own geometry (tools/
   * mkmesh.py from an STL: milli ints, 9 per triangle) and hands it to
   * the walker once after glInit; the name is then an Ent mesh id like
   * cube / plane / sphere.  Returns the triangle count, -1 malformed.
   * NULL without gfx, like the other gfx slots. */
  int64_t (*gfx_mesh_load)(const char *name, const char *text, uint64_t len);

  /* ---- v9 additions (appended: earlier offsets unchanged) -----------
   * the music channel (snd_raw.h): one MP3 beside the .qa, decoded by
   * the host as it plays, looped, under the effects at vol/1000. */
  int (*snd_music)(const char *path, int64_t vol);

  /* ---- v10 additions (appended: earlier offsets unchanged) ----------
   * the 2D layer: render the scene, then a List of Ent in scene2d's
   * pixel space (the Int camera at dist milli) over it with the depth
   * cleared -- a UI on top of a 3D board, one present. */
  int (*gfx_render_ui)(uint64_t scene, uint64_t ui, int64_t dist, int64_t *draws, int64_t *dyn_bytes);

  /* ---- v11 additions (appended: earlier offsets unchanged) ----------
   * the wall clock: seconds since 1970-01-01 UTC, for records that a
   * person will read back (a receipt's time).  0 where the host has no
   * clock; the monotonic mtime stays the timer. */
  int64_t (*clock_now)(void);
} qos_hal_t;

/* ---- the memory-growth grant (RETIRED in v12) ----------------------
 * Layout-identical to fpr_grant_t (fpr.h) on both sides; the boot
 * record keeps the slot for layout stability, but a v12 host sets it
 * NULL: the app owns its arena and never asks the host for memory. */
typedef struct {
  void *ptr; /* NULL = denied */
  uint64_t size;
} qos_grant_t;

/* ---- the boot record ------------------------------------------------
 * Everything the Loader stage hands the app, in one versioned struct
 * (the ABI can grow by appending fields; abi_version gates readers).
 * caps is System.qa's serialized grant format unchanged:
 * "appid\nurl mode\n" lines (docs/QA-FORMAT.md) -- the FPRISC side
 * reads it via Sys.caps and enforces its own gate, equal strength to
 * the bare-metal process model since neither has hardware behind it. */
typedef struct {
  uint64_t abi_version;
  const qos_hal_t *hal;
  void *heap_base; /* v1..v11: the app's first slab (slot space past the
                    * image).  v12: unused (0) -- see arena_base below */
  uint64_t heap_size;
  qos_grant_t (*grow)(uint64_t want_bytes); /* v12: NULL (retired) */
  const unsigned char *caps;
  uint64_t caps_len;
  /* the storage syscall channel, tag-compatible with System.qa's
   * trampoline (process.c): 2 = kv append, 3 = kv replay */
  int64_t (*syscall_fn)(uint64_t tag, const char *pay, uint64_t len,
                        char *out, uint64_t outcap);
  /* ---- v2 additions (appended: v1 offsets unchanged) ----------------
   * tls_off: the TLS BORROW.  The app image carries no TLS block, but
   * multi-hart needs a per-hart-thread cell for the hart pointer (and
   * the x64 a6/a7 arg-staging cells).  qosp declares one __thread
   * borrow block per hart thread --
   *
   *     struct { void *hart; uint64_t a6, a7; }   (offsets 0/8/16)
   *
   * -- and publishes its displacement from the thread pointer here.
   * The executable's static TLS block sits at the SAME displacement in
   * every thread, so one constant serves all harts; --target=qx64/qa64
   * code reads it from the plain global fpr_g_tlsoff (entry.c copies
   * it there before anything else runs), and fpr.h's FPR_QOSAPP
   * accessors give the C-side runtime the same view. */
  uint64_t tls_off;
  /* ---- v12 additions (appended: earlier offsets unchanged) ----------
   * THE APP OWNS ITS ARENA.  [arena_base, arena_base + arena_size) is
   * every byte of the mapped arena past the loaded image -- the slot
   * tail, the plugin window, and the rest -- and the app runs its own
   * buddy over it (reserving the plugin window itself, since it knows
   * QOS_PLUG_BASE), behind its memory actor.  The host keeps no
   * allocator over the arena: plugin loads write into the fixed window
   * (syscall tag 4), nothing else.  The first slab, every growth, and
   * every free happen inside the app; the host's grow callback and its
   * mutex are gone with them. */
  void *arena_base;
  uint64_t arena_size;
} qos_boot_t;

/* ---- the entry ------------------------------------------------------
 * ENTRY(qos_app_entry) in link-qosapp.ld: the loader reads it from
 * e_entry, the way any ELF loader would.  A plain callable function,
 * same philosophy as fpr_process_entry -- we are being called by an
 * already-running host, not booting hardware.  The app's main-actor
 * result is RENDERED (str) into result_out (truncated to result_cap,
 * NUL-terminated) rather than returned as a V: the host has no FPRISC
 * runtime to interpret a V with, and the string form is what it would
 * print anyway.  Returns 0 on clean completion. */
typedef int64_t (*qos_app_entry_t)(const qos_boot_t *boot, char *result_out,
                                   uint64_t result_cap);

#endif /* QOS_ABI_H */
