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
 *   - one virtqueue, one outstanding request, synchronous poll for
 *     completion — the UART discipline again. A request is the standard
 *     3-descriptor chain: 16-byte header, 4 KiB data, 1 status byte.
 *   - no feature negotiation beyond VERSION_1 on modern: we need none
 *     of RO/FLUSH/SEG_MAX for a PoC, and QEMU is fine with that.
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

static int blk_probe(void) {
  for (int i = 0; i < VIRTIO_NSLOTS; i++) {
    blk = (volatile u32 *)(VIRTIO_SLOT0 + i * VIRTIO_STRIDE);
    if (rr(R_MAGIC) != 0x74726976) continue;
    if (rr(R_DEVICEID) != 2) continue;      /* 2 = virtio-blk */
    blk_version = rr(R_VERSION);
    if (blk_version != 1 && blk_version != 2) continue;

    wr(R_STATUS, 0);                        /* reset */
    wr(R_STATUS, ST_ACK);
    wr(R_STATUS, ST_ACK | ST_DRIVER);
    wr(R_DRVFEATSEL, 0);
    wr(R_DRVFEAT, 0);                       /* accept no feature bits 0..31 */
    if (blk_version == 2) {
      wr(R_DEVFEATSEL, 1);
      u32 feat1 = rr(R_DEVFEAT);
      wr(R_DRVFEATSEL, 1);
      wr(R_DRVFEAT, feat1 & 1u);            /* VIRTIO_F_VERSION_1 */
      wr(R_STATUS, ST_ACK | ST_DRIVER | ST_FEAT_OK);
      if (!(rr(R_STATUS) & ST_FEAT_OK)) fpr_cpanic("blk: FEATURES_OK refused");
    } else {
      wr(R_GUESTPAGESZ, 4096);
    }

    /* capacity: u64 sector count at config+0, byte reads for alignment */
    blk_sectors = 0;
    for (int b = 7; b >= 0; b--)
      blk_sectors = (blk_sectors << 8) | ((volatile u8 *)blk)[R_CONFIG + b];

    vq_setup();
    wr(R_STATUS, ST_ACK | ST_DRIVER | (blk_version == 2 ? ST_FEAT_OK : 0) | ST_DRIVER_OK);

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

/* one synchronous page transfer through the 3-descriptor chain */
static void blk_rw(u64 page, int is_write) {
  if (!blk) fpr_cpanic("blk: no disk (boot QEMU with `make run-disk`)");
  if ((page + 1) * SEC_PER_PAGE > blk_sectors) fpr_cpanic("blk: page out of range");

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
  av->ring[q.avail_shadow % QSZ] = 0;
  FENCE();
  av->idx = ++q.avail_shadow;
  FENCE();
  wr(R_QNOTIFY, 0);
  for (u32 spin = 0; spin < 40000000; spin++) {   /* sync completion */
    FENCE();
    if (QUSED->idx != before) break;
  }
  if (QUSED->idx == before) fpr_cpanic("blk: request timed out");
  q.last_used = QUSED->idx;
  wr(R_INTACK, 3);
  FENCE();
  if (bstatus != 0) fpr_cpanic("blk: device reported I/O error");
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
  blk_rw((u64)UNTAG(pv), 0);
  return (V)fpr_mkstr(bdata, PAGE_SZ);
}

static V h_blkWrite(V d, V pv, V sv) {
  (void)d;
  if (!ISINT(pv)) fpr_cpanic("blkWrite: page must be an Int");
  if (ISINT(sv) || TID(sv) != T_STR) fpr_cpanic("blkWrite: payload must be a String");
  str_t *s = (str_t *)sv;
  if (s->len > PAGE_SZ) fpr_cpanic("blkWrite: payload exceeds one page");
  for (u64 i = 0; i < PAGE_SZ; i++) bdata[i] = i < s->len ? s->bytes[i] : 0;
  blk_rw((u64)UNTAG(pv), 1);
  return TAG((sw)s->len);
}

FPR_FN(fpr_g_blkPages, h_blkPages, 1);
FPR_FN(fpr_g_blkRead, h_blkRead, 2);
FPR_FN(fpr_g_blkWrite, h_blkWrite, 3);
