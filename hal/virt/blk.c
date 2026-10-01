/* blk.c — the disk HAL module: virtio-blk, PAGE-granular, policy-free.
 *
 * The contract is deliberately dumb: the disk is an array of 4 KiB PAGES
 * (8 virtio sectors each), read and written whole. No log, no records, no
 * index, no files — every one of those is POLICY and lives in FPRISC
 * (see programs/diskfs.fpr). The HAL will happily read or overwrite any
 * page directly; that the filesystem above chooses to only ever APPEND
 * is the filesystem's discipline, not the driver's.
 *
 * FPRISC surface (fpr_g_* discoverable symbols, same shape as net.c):
 *   blkPages d        -> Int      capacity in 4 KiB pages
 *   blkRead d p       -> String   the 4096 bytes of page p
 *   blkWrite d p s    -> Int      write s (<= 4096 bytes, zero-padded)
 *                                 to page p; returns bytes accepted
 *
 * A page read materializes as a 4096-byte String on the FPRISC heap:
 * "streaming" is the FPRISC pattern of read page -> inspect -> drop,
 * page by page, which is why runtime.c's free-list classes now reach
 * 8 KiB (a page String + headers must be reclaimable on drop).
 *
 * Driver notes:
 *   - same virtio-mmio probe as net.c (legacy v1 + modern v2), but
 *     DeviceID 2; the two probes scan the same 8 slots and claim
 *     different devices, so net + blk coexist.
 *   - one virtqueue, one outstanding request, actor-parked timed poll for
 *     completion — the UART discipline again. A request is the standard
 *     3-descriptor chain: 16-byte header, 4 KiB data, 1 status byte.
 *   - no feature negotiation beyond VERSION_1 on modern: we need none
 *     of RO/FLUSH/SEG_MAX for a PoC, and QEMU is fine with that.
 *
 * Failure (2026-10-01, docs/2026-10-01-DISK-HARDENING.md): nothing here
 * halts the machine and nothing waits without a deadline.  A request the
 * device does not complete within BLK_DEADLINE, an I/O error, a missing
 * disk or an out-of-range page FAIL-STOPS the calling actor
 * (fpr_actor_fail: its RPC callers hear "dead actor").  The DMA buffers of
 * a request the device may still be working on stay reserved until the
 * used ring shows it complete or a reset is confirmed; a stalled orphan is
 * reset by the next caller once it is older than the deadline, and a
 * device that does not come back from reset takes the disk OFFLINE --
 * every later request is refused at once.
 */
#include "fpr.h"

typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;

#define FENCE() __asm__ volatile("fence rw, rw" ::: "memory")
#define FENCE_IO() __asm__ volatile("fence io, io" ::: "memory")

static void bputs(const char *s) { while (*s) hal_putc(*s++); }
static void bputdec(u64 v) {
  char b[24]; int n = 0;
  do { b[n++] = '0' + (v % 10); v /= 10; } while (v);
  while (n) hal_putc(b[--n]);
}

/* ---- virtio-mmio (register map identical to net.c) -------------------- */
#define VIRTIO_SLOT0   0x10001000UL
#define VIRTIO_NSLOTS  8
#define VIRTIO_STRIDE  0x1000UL

#define R_MAGIC        0x000
#define R_VERSION      0x004
#define R_DEVICEID     0x008
#define R_DEVFEAT      0x010
#define R_DEVFEATSEL   0x014
#define R_DRVFEAT      0x020
#define R_DRVFEATSEL   0x024
#define R_GUESTPAGESZ  0x028  /* legacy */
#define R_QSEL         0x030
#define R_QNUMMAX      0x034
#define R_QNUM         0x038
#define R_QALIGN       0x03c  /* legacy */
#define R_QPFN         0x040  /* legacy */
#define R_QREADY       0x044  /* modern */
#define R_QNOTIFY      0x050
#define R_INTACK       0x064
#define R_STATUS       0x070
#define R_QDESCLO      0x080  /* modern */
#define R_QDESCHI      0x084
#define R_QAVAILLO     0x090
#define R_QAVAILHI     0x094
#define R_QUSEDLO      0x0a0
#define R_QUSEDHI      0x0a4
#define R_CONFIG       0x100

#define ST_ACK        1
#define ST_DRIVER     2
#define ST_DRIVER_OK  4
#define ST_FEAT_OK    8

static volatile u32 *blk;   /* MMIO base, NULL until probed */
static int blk_version;     /* 1 legacy, 2 modern */
static u64 blk_sectors;     /* capacity from config space */

static u32 rr(u32 off) { FENCE_IO(); u32 v = blk[off / 4]; FENCE_IO(); return v; }
static void wr(u32 off, u32 v) { FENCE_IO(); blk[off / 4] = v; FENCE_IO(); }

/* split virtqueue, same static layout trick as net.c */
#define QSZ 8
typedef struct { u64 addr; u32 len; u16 flags; u16 next; } __attribute__((packed)) vq_desc_t;
typedef struct { u16 flags, idx, ring[QSZ], used_event; } __attribute__((packed)) vq_avail_t;
typedef struct { u32 id, len; } __attribute__((packed)) vq_uelem_t;
typedef struct { u16 flags, idx; vq_uelem_t ring[QSZ]; u16 avail_event; } __attribute__((packed)) vq_used_t;
#define D_NEXT  1
#define D_WRITE 2

static struct {
  u8 mem[8192] __attribute__((aligned(4096)));
  u16 last_used;
  u16 avail_shadow;
} q;
#define QDESC  ((volatile vq_desc_t *)(q.mem))
#define QAVAIL ((volatile vq_avail_t *)(q.mem + QSZ * 16))
#define QUSED  ((volatile vq_used_t *)(q.mem + 4096))

/* ---- the page geometry: THE contract ---------------------------------- */
#define PAGE_SZ   4096
#define SEC_SZ    512
#define SEC_PER_PAGE (PAGE_SZ / SEC_SZ)

/* one outstanding request: header + data + status, physically static */
#define BLK_T_IN  0   /* device -> memory (read)  */
#define BLK_T_OUT 1   /* memory -> device (write) */
static struct { u32 type, reserved; u64 sector; } __attribute__((packed, aligned(16))) breq;
static u8 bdata[PAGE_SZ] __attribute__((aligned(PAGE_SZ)));
static u8 bstatus __attribute__((aligned(16)));

/* The deadline: how long a request may take before the device counts as
 * stalled, in 10 MHz CLINT ticks (5 s); a test build shortens it.  Without
 * a usable clock (early boot) the same wait is counted in 200 us parks. */
#ifndef BLK_DEADLINE_TICKS
#define BLK_DEADLINE_TICKS 50000000ULL
#endif
#define BLK_DEADLINE_PARKS (BLK_DEADLINE_TICKS / 2000ULL)

/* busy: the DMA buffers belong to a request (held by its owner, or by an
 * orphan).  orphan: 1 = the owner is gone and the device may still be
 * using the buffers; 2 = one waiter is resetting the device.  offline: a
 * reset did not bring the device back. */
static unsigned blk_busy, blk_orphan, blk_offline;
static u16 blk_before;
static uint64_t blk_since; /* mtime the request in flight was submitted */

#ifdef QOS_BLK_TEST
/* test-only (never in an ordinary build): withhold the doorbell of the
 * next request (a device that never completes it), and make the next
 * reset fail to come back */
static unsigned blk_test_stall, blk_test_reset_fails;
static V h_blkTestStall(V u) { (void)u; blk_test_stall = 1; return TAG(0); }
static V h_blkTestResetFails(V u) { (void)u; blk_test_reset_fails = 1; return TAG(0); }
FPR_FN(fpr_g_blkTestStall, h_blkTestStall, 1);
FPR_FN(fpr_g_blkTestResetFails, h_blkTestResetFails, 1);
/* the machine clock, in microseconds (10 MHz CLINT) */
static V h_blkTestNow(V u) { (void)u; return TAG((sw)(hal_mtime() / 10)); }
FPR_FN(fpr_g_blkTestNow, h_blkTestNow, 1);
#endif

static uint64_t blk_elapsed(uint64_t since) {
  uint64_t now = hal_mtime();
  return (since && now) ? now - since : 0;
}

/* a killed owner: the request stays in flight, its buffers reserved */
static void blk_abandon(void *unused) {
  (void)unused;
  __atomic_store_n(&blk_orphan, 1, __ATOMIC_RELEASE);
}

static int blk_init(void);

/* Reset, CONFIRMED: after the driver writes 0 the device may not touch the
 * queue or the buffers again once it reads back 0 (virtio 1.x, 4.2.2.1).
 * Only then is the queue rebuilt and the buffers free.  1 = the device is
 * back. */
static int blk_reset(void) {
  wr(R_STATUS, 0);
  int confirmed = 0;
  for (int i = 0; i < 1000; i++) {
    if (rr(R_STATUS) == 0) { confirmed = 1; break; }
    fpr_actor_sleep_us(100);
  }
#ifdef QOS_BLK_TEST
  if (blk_test_reset_fails) { blk_test_reset_fails = 0; confirmed = 0; }
#endif
  if (!confirmed) return 0;
  return blk_init();
}

static void blk_lock(void) {
  uint64_t t0 = hal_mtime();
  uint64_t parks = 0;
  for (;;) {
    if (__atomic_load_n(&blk_offline, __ATOMIC_ACQUIRE))
      fpr_actor_fail("blk: the disk is offline (a stalled request could not be reset) -- request refused");
    unsigned free = 0;
    if (__atomic_compare_exchange_n(&blk_busy, &free, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) break;
    /* A killed or timed-out owner cannot release DMA storage before the
     * device is done with it: completion, or a confirmed reset. */
    if (__atomic_load_n(&blk_orphan, __ATOMIC_ACQUIRE) == 1) {
      FENCE();
      unsigned abandoned = 1;
      if (QUSED->idx != blk_before) {
        if (__atomic_compare_exchange_n(&blk_orphan, &abandoned, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
          q.last_used = QUSED->idx;
          wr(R_INTACK, 3);
          __atomic_store_n(&blk_busy, 0, __ATOMIC_RELEASE);
        }
      } else if ((blk_since ? blk_elapsed(blk_since) >= BLK_DEADLINE_TICKS : parks >= BLK_DEADLINE_PARKS) &&
                 __atomic_compare_exchange_n(&blk_orphan, &abandoned, 2, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
        /* the orphan is past the deadline: the device stalled */
        if (blk_reset()) {
          bputs("[blk] the device stalled on an abandoned request; reset, that request was dropped\n");
          __atomic_store_n(&blk_orphan, 0, __ATOMIC_RELEASE);
          __atomic_store_n(&blk_busy, 0, __ATOMIC_RELEASE);
        } else {
          /* still possibly DMA-ing: the buffers stay reserved for good */
          bputs("[blk] the device stalled and did not come back from reset: disk offline\n");
          __atomic_store_n(&blk_offline, 1, __ATOMIC_RELEASE);
          __atomic_store_n(&blk_orphan, 0, __ATOMIC_RELEASE);
          fpr_actor_fail("blk: the device stalled and did not come back from reset -- disk offline");
        }
        continue;
      }
    } else if (t0 ? blk_elapsed(t0) >= 3 * BLK_DEADLINE_TICKS : parks >= 3 * BLK_DEADLINE_PARKS) {
      /* a live owner has its own deadline, after which the buffers become
       * an orphan's; waiting three deadlines means something is wrong */
      fpr_actor_fail("blk: waited three deadlines for the disk -- request refused");
    }
    parks++;
    fpr_actor_sleep_us(200);
  }
  fpr_actor_cleanup_set(blk_abandon, &blk_busy);
}
static void blk_unlock(void) {
  fpr_actor_cleanup_clear(&blk_busy);
  __atomic_store_n(&blk_busy, 0, __ATOMIC_RELEASE);
}

static void vq_setup(void) {
  for (u32 i = 0; i < sizeof(q.mem); i++) q.mem[i] = 0;
  q.last_used = 0;
  q.avail_shadow = 0;
  wr(R_QSEL, 0);
  if (rr(R_QNUMMAX) < QSZ) fpr_cpanic("blk: queue too small");
  wr(R_QNUM, QSZ);
  if (blk_version == 1) {
    wr(R_QALIGN, 4096);
    wr(R_QPFN, (u32)(((u64)(uintptr_t)q.mem) >> 12));
  } else {
    u64 d = (u64)(uintptr_t)QDESC, a = (u64)(uintptr_t)QAVAIL, u = (u64)(uintptr_t)QUSED;
    wr(R_QDESCLO, (u32)d);  wr(R_QDESCHI, (u32)(d >> 32));
    wr(R_QAVAILLO, (u32)a); wr(R_QAVAILHI, (u32)(a >> 32));
    wr(R_QUSEDLO, (u32)u);  wr(R_QUSEDHI, (u32)(u >> 32));
    wr(R_QREADY, 1);
  }
}

/* bring a reset device up: status handshake, features, the queue, DRIVER_OK
 * (boot, and recovery after a stalled request).  0 = the device refused */
static int blk_init(void) {
  wr(R_STATUS, ST_ACK);
  wr(R_STATUS, ST_ACK | ST_DRIVER);
  wr(R_DRVFEATSEL, 0);
  wr(R_DRVFEAT, 0);                         /* accept no feature bits 0..31 */
  if (blk_version == 2) {
    wr(R_DEVFEATSEL, 1);
    u32 feat1 = rr(R_DEVFEAT);
    wr(R_DRVFEATSEL, 1);
    wr(R_DRVFEAT, feat1 & 1u);              /* VIRTIO_F_VERSION_1 */
    wr(R_STATUS, ST_ACK | ST_DRIVER | ST_FEAT_OK);
    if (!(rr(R_STATUS) & ST_FEAT_OK)) return 0;
  } else {
    wr(R_GUESTPAGESZ, 4096);
  }
  vq_setup();
  wr(R_STATUS, ST_ACK | ST_DRIVER | (blk_version == 2 ? ST_FEAT_OK : 0) | ST_DRIVER_OK);
  return 1;
}

static int blk_probe(void) {
  for (int i = 0; i < VIRTIO_NSLOTS; i++) {
    blk = (volatile u32 *)(VIRTIO_SLOT0 + i * VIRTIO_STRIDE);
    if (rr(R_MAGIC) != 0x74726976) continue;
    if (rr(R_DEVICEID) != 2) continue;      /* 2 = virtio-blk */
    blk_version = rr(R_VERSION);
    if (blk_version != 1 && blk_version != 2) continue;

    wr(R_STATUS, 0);                        /* reset */
    if (!blk_init()) fpr_cpanic("blk: FEATURES_OK refused");

    /* capacity: u64 sector count at config+0, byte reads for alignment */
    blk_sectors = 0;
    for (int b = 7; b >= 0; b--)
      blk_sectors = (blk_sectors << 8) | ((volatile u8 *)blk)[R_CONFIG + b];

    bputs("[blk] virtio-blk v");
    hal_putc('0' + blk_version);
    bputs(" slot ");
    hal_putc('0' + i);
    bputs(", ");
    bputdec(blk_sectors / SEC_PER_PAGE);
    bputs(" pages of 4096 bytes\n");
    return 1;
  }
  blk = 0;
  return 0;
}

/* one page transfer through the 3-descriptor chain; the caller holds the
 * lock.  On return the transfer is complete and the status good; every
 * other outcome fail-stops the caller (see the header). */
static void blk_rw(u64 page, int is_write) {

  breq.type = is_write ? BLK_T_OUT : BLK_T_IN;
  breq.reserved = 0;
  breq.sector = page * SEC_PER_PAGE;
  bstatus = 0xff;

  volatile vq_desc_t *d = QDESC;
  d[0].addr = (u64)(uintptr_t)&breq;   d[0].len = 16;      d[0].flags = D_NEXT;                          d[0].next = 1;
  d[1].addr = (u64)(uintptr_t)bdata;   d[1].len = PAGE_SZ; d[1].flags = (u16)(D_NEXT | (is_write ? 0 : D_WRITE)); d[1].next = 2;
  d[2].addr = (u64)(uintptr_t)&bstatus; d[2].len = 1;      d[2].flags = D_WRITE;                         d[2].next = 0;

  volatile vq_avail_t *av = QAVAIL;
  u16 before = QUSED->idx;
  blk_before = before;
  av->ring[q.avail_shadow % QSZ] = 0;
  FENCE();
  av->idx = ++q.avail_shadow;
  FENCE();
  uint64_t start = hal_mtime();
  blk_since = start;
#ifdef QOS_BLK_TEST
  if (blk_test_stall) blk_test_stall = 0; else
#endif
  wr(R_QNOTIFY, 0);
  uint64_t parks = 0;
  for (;;) {
    FENCE();
    if (QUSED->idx != before) break;
    if (start ? blk_elapsed(start) >= BLK_DEADLINE_TICKS : ++parks >= BLK_DEADLINE_PARKS) {
      /* the device may still DMA into the buffers: they stay reserved (an
       * orphan) until it completes or a later caller resets it */
      fpr_actor_cleanup_clear(&blk_busy);
      __atomic_store_n(&blk_orphan, 1, __ATOMIC_RELEASE);
      fpr_actor_fail("blk: request timed out (the device stalled); its buffers stay reserved until it completes or is reset");
    }
    fpr_actor_sleep_us(200);
  }
  q.last_used = QUSED->idx;
  wr(R_INTACK, 3);
  FENCE();
  if (bstatus != 0) {
    blk_unlock();
    fpr_actor_fail("blk: device reported an I/O error");
  }
}

/* a request that cannot be made: refused, the caller fail-stops */
static void blk_check(V pv) {
  if (!blk) fpr_actor_fail("blk: no disk (boot QEMU with `make run-disk`)");
  if ((u64)UNTAG(pv) >= blk_sectors / SEC_PER_PAGE) fpr_actor_fail("blk: page out of range");
}

/* ---- device table hook + FPRISC surface -------------------------------- */
void blk_setup(void) {
  static int done;
  if (done) return;
  done = 1;
  if (!blk_probe()) bputs("[blk] no virtio-blk device found\n");
}

static V h_blkPages(V d) {
  (void)d;
  return TAG(blk ? (sw)(blk_sectors / SEC_PER_PAGE) : 0);
}

static V h_blkRead(V d, V pv) {
  (void)d;
  if (!ISINT(pv)) fpr_cpanic("blkRead: page must be an Int");
  blk_check(pv);
  blk_lock();
  blk_rw((u64)UNTAG(pv), 0);
  V result = (V)fpr_mkstr(bdata, PAGE_SZ);
  blk_unlock();
  return result;
}

static V h_blkWrite(V d, V pv, V sv) {
  (void)d;
  if (!ISINT(pv)) fpr_cpanic("blkWrite: page must be an Int");
  if (ISINT(sv) || TID(sv) != T_STR) fpr_cpanic("blkWrite: payload must be a String");
  str_t *s = (str_t *)sv;
  if (s->len > PAGE_SZ) fpr_cpanic("blkWrite: payload exceeds one page");
  blk_check(pv);
  blk_lock();
  for (u64 i = 0; i < PAGE_SZ; i++) bdata[i] = i < s->len ? s->bytes[i] : 0;
  blk_rw((u64)UNTAG(pv), 1);
  blk_unlock();
  return TAG((sw)s->len);
}

FPR_FN(fpr_g_blkPages, h_blkPages, 1);
FPR_FN(fpr_g_blkRead, h_blkRead, 2);
FPR_FN(fpr_g_blkWrite, h_blkWrite, 3);
