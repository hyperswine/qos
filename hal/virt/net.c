/* net.c — the network HAL module: virtio-net + a PoC transport.
 *
 * Two layers, one honest boundary:
 *
 *  1. virtio-net MMIO driver (both legacy v1 and modern v2 register
 *     layouts): probes the virt machine's 8 virtio-mmio slots, brings up
 *     RX/TX split virtqueues in static memory, moves Ethernet frames.
 *     Polled, no interrupts; a transmit parks the sending actor until
 *     the device completes it (never the hart), with a deadline.
 *
 *  2. A minimal transport so FPRISC can speak to the host: ARP responder,
 *     IPv4 (no fragments), and a small-table (NETCONN) TCP with no retransmit,
 *     no congestion control, and fire-and-forget sends. This is a QEMU
 *     slirp demonstration: raw FP-RISC policy on RV64 (netpolicy.fpr),
 *     legacy C transport on RV32. RV64 exposes frame-only mechanisms to
 *     std/net, the protocol actor. The legacy native net API refuses bypasses.
 *
 * FPRISC surface (every unknown FPRISC name links against fpr_g_*):
 *   netPoll 0    -> Int     pump the NIC; the next connection id
 *                           (1..NETCONN) with buffered request bytes,
 *                           else 0 (fair rotation across peers)
 *   netRead c    -> String  drain up to 1 KiB of connection c
 *   netWrite c s -> Int     send s on connection c (segmented)
 *   netClose c   -> Int     FIN and release connection c's slot
 *
 * Static identity (slirp defaults, no DHCP — PoC simplification):
 *   guest 10.0.2.15, gateway 10.0.2.2, MAC from device config space.
 */
#include "fpr.h"
#if __riscv_xlen == 64
#include "virtio.h"
#endif

/* ---- tiny freestanding helpers ---------------------------------------- */
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;

static void ncpy(u8 *d, const u8 *s, u32 n) { while (n--) *d++ = *s++; }
static void nset(u8 *d, u8 v, u32 n) { while (n--) *d++ = v; }
static int neq(const u8 *a, const u8 *b, u32 n) { while (n--) if (*a++ != *b++) return 0; return 1; }
static u16 htons16(u16 v) { return (u16)((v << 8) | (v >> 8)); }
static u32 htonl32(u32 v) {
  return ((v & 0xff) << 24) | ((v & 0xff00) << 8) | ((v >> 8) & 0xff00) | (v >> 24);
}
#define FENCE() __asm__ volatile("fence rw, rw" ::: "memory")
#define FENCE_IO() __asm__ volatile("fence io, io" ::: "memory")

/* dbg console (bypasses FPRISC, boot-time only) */
static void nputs(const char *s) { while (*s) hal_putc(*s++); }
static void nputhex(u64 v, int digits) {
  for (int i = digits - 1; i >= 0; i--) {
    int d = (v >> (i * 4)) & 0xf;
    hal_putc(d < 10 ? '0' + d : 'a' + d - 10);
  }
}

/* ---- virtio-mmio ------------------------------------------------------- */
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

#define F_NET_MAC     (1u << 5)

static volatile u32 *nic;   /* MMIO base, NULL until probed */
static int nic_version;     /* 1 legacy, 2 modern */
static int vhdr_len;        /* 10 legacy (no MRG_RXBUF), 12 modern */
static u8 our_mac[6];

static u32 rr(u32 off) { FENCE_IO(); u32 v = nic[off / 4]; FENCE_IO(); return v; }
static void wr(u32 off, u32 v) { FENCE_IO(); nic[off / 4] = v; FENCE_IO(); }

/* split virtqueue, QSZ descriptors, legacy page layout (works for modern
 * too since modern takes explicit addresses): desc+avail | page | used */
#define QSZ 8
typedef struct { u64 addr; u32 len; u16 flags; u16 next; } __attribute__((packed)) vq_desc_t;
typedef struct { u16 flags, idx, ring[QSZ], used_event; } __attribute__((packed)) vq_avail_t;
typedef struct { u32 id, len; } __attribute__((packed)) vq_uelem_t;
typedef struct { u16 flags, idx; vq_uelem_t ring[QSZ]; u16 avail_event; } __attribute__((packed)) vq_used_t;
#define D_NEXT  1
#define D_WRITE 2

typedef struct {
  u8 mem[8192] __attribute__((aligned(4096)));
  u16 last_used;
  u16 avail_shadow;
} vq_t;
static vq_t q_rx, q_tx;
#define QDESC(q)  ((volatile vq_desc_t *)((q)->mem))
#define QAVAIL(q) ((volatile vq_avail_t *)((q)->mem + QSZ * 16))
#define QUSED(q)  ((volatile vq_used_t *)((q)->mem + 4096))

#define FRAMESZ 1792
static u8 rx_bufs[QSZ][FRAMESZ + 12] __attribute__((aligned(16)));
static u8 tx_buf[FRAMESZ + 12] __attribute__((aligned(16)));

static void vq_setup(int qi, vq_t *q) {
  nset(q->mem, 0, sizeof(q->mem));
  q->last_used = 0;
  q->avail_shadow = 0;
#if __riscv_xlen == 64
  if (!qos_virtio_queue(nic, qi, QSZ, q->mem)) fpr_cpanic("net: queue too small");
#else
  wr(R_QSEL, qi);
  if (rr(R_QNUMMAX) < QSZ) fpr_cpanic("net: queue too small");
  wr(R_QNUM, QSZ);
  if (nic_version == 1) {
    wr(R_QALIGN, 4096);
    wr(R_QPFN, (u32)(((u64)(uintptr_t)q->mem) >> 12));
  } else {
    u64 d = (u64)(uintptr_t)QDESC(q), a = (u64)(uintptr_t)QAVAIL(q), u = (u64)(uintptr_t)QUSED(q);
    wr(R_QDESCLO, (u32)d);  wr(R_QDESCHI, (u32)(d >> 32));
    wr(R_QAVAILLO, (u32)a); wr(R_QAVAILHI, (u32)(a >> 32));
    wr(R_QUSEDLO, (u32)u);  wr(R_QUSEDHI, (u32)(u >> 32));
    wr(R_QREADY, 1);
  }
#endif
}

static void rx_post(int i) {
  volatile vq_desc_t *d = &QDESC(&q_rx)[i];
  d->addr = (u64)(uintptr_t)rx_bufs[i];
  d->len = FRAMESZ + vhdr_len;
  d->flags = D_WRITE;
  d->next = 0;
  volatile vq_avail_t *av = QAVAIL(&q_rx);
  av->ring[q_rx.avail_shadow % QSZ] = i;
  FENCE();
  av->idx = ++q_rx.avail_shadow;
  FENCE();
  wr(R_QNOTIFY, 0);
}

#if __riscv_xlen == 64
static int net_probe(void) {
  nic = qos_virtio_probe(1);
  if (!nic) return 0;
  nic_version = rr(R_VERSION);
  wr(R_STATUS, 0);
  if (!qos_virtio_negotiate(nic, F_NET_MAC)) fpr_cpanic("net: FEATURES_OK refused");
  vhdr_len = nic_version == 2 ? 12 : 10;
  for (int b = 0; b < 6; b++) our_mac[b] = ((volatile u8 *)nic)[R_CONFIG + b];
  vq_setup(0, &q_rx); vq_setup(1, &q_tx);
  qos_virtio_ready(nic);
  for (int b = 0; b < QSZ; b++) rx_post(b);
  nputs("[net] virtio-net v"); hal_putc('0' + nic_version);
  nputs(" slot "); hal_putc('0' + ((uintptr_t)nic - VIRTIO_SLOT0) / VIRTIO_STRIDE);
  nputs(" mac ");
  for (int b = 0; b < 6; b++) { nputhex(our_mac[b], 2); if (b < 5) hal_putc(':'); }
  nputs("\n");
  return 1;
}
#else
static int net_probe(void) {
  for (int i = 0; i < VIRTIO_NSLOTS; i++) {
    volatile u32 *base = (volatile u32 *)(VIRTIO_SLOT0 + i * VIRTIO_STRIDE);
    nic = base;
    if (rr(R_MAGIC) != 0x74726976) continue;
    if (rr(R_DEVICEID) != 1) continue;
    nic_version = rr(R_VERSION);
    if (nic_version != 1 && nic_version != 2) continue;

    wr(R_STATUS, 0);                       /* reset */
    wr(R_STATUS, ST_ACK);
    wr(R_STATUS, ST_ACK | ST_DRIVER);
    wr(R_DEVFEATSEL, 0);
    u32 feat0 = rr(R_DEVFEAT);
    wr(R_DRVFEATSEL, 0);
    wr(R_DRVFEAT, feat0 & F_NET_MAC);      /* accept only F_MAC */
    if (nic_version == 2) {
      wr(R_DEVFEATSEL, 1);
      u32 feat1 = rr(R_DEVFEAT);
      wr(R_DRVFEATSEL, 1);
      wr(R_DRVFEAT, feat1 & 1u);           /* VIRTIO_F_VERSION_1 (bit 32) */
      wr(R_STATUS, ST_ACK | ST_DRIVER | ST_FEAT_OK);
      if (!(rr(R_STATUS) & ST_FEAT_OK)) fpr_cpanic("net: FEATURES_OK refused");
      vhdr_len = 12;
    } else {
      wr(R_GUESTPAGESZ, 4096);
      vhdr_len = 10;
    }
    for (int b = 0; b < 6; b++)
      our_mac[b] = ((volatile u8 *)nic)[R_CONFIG + b];

    vq_setup(0, &q_rx);
    vq_setup(1, &q_tx);
    wr(R_STATUS, ST_ACK | ST_DRIVER | (nic_version == 2 ? ST_FEAT_OK : 0) | ST_DRIVER_OK);
    for (int b = 0; b < QSZ; b++) rx_post(b);

    nputs("[net] virtio-net v");
    hal_putc('0' + nic_version);
    nputs(" slot ");
    hal_putc('0' + i);
    nputs(" mac ");
    for (int b = 0; b < 6; b++) { nputhex(our_mac[b], 2); if (b < 5) hal_putc(':'); }
    nputs("\n");
    return 1;
  }
  nic = 0;
  return 0;
}
#endif

/* ---- the transmit buffer: one owner, a parked wait for completion -------
 * tx_buf holds one frame.  A sender takes it (tx_take), builds the frame,
 * notifies the device and PARKS (fpr_actor_sleep_us) between checks of the
 * used ring, so the hart serves other actors meanwhile; QEMU completes
 * within microseconds, so a short bounded spin catches most frames before
 * the first park.  Until 2026-10-02 this was a 4,000,000-iteration spin
 * holding the hart on every netWrite (docs/2026-10-02-QOS-AUDIT.md).
 *
 * Failure follows the disk's rule (docs/2026-10-01-DISK-HARDENING.md): a
 * frame the device does not complete within NET_DEADLINE takes the network
 * OFFLINE -- the buffer may still be read by DMA, so it is never reused --
 * and fail-stops the caller; every later send is refused the same way.  A
 * sender killed while it owns the buffer leaves it an ORPHAN: the next
 * sender reclaims it once the used ring shows that frame complete, or takes
 * the network offline when it is past the deadline. */
#ifndef NET_DEADLINE_TICKS
#define NET_DEADLINE_TICKS 50000000ULL /* 5 s at the virt CLINT's 10 MHz */
#endif
#define NET_DEADLINE_PARKS (NET_DEADLINE_TICKS / 2000ULL) /* when mtime reads 0 */
static unsigned tx_busy, tx_orphan, net_offline;
#ifdef QOS_NET_TEST
/* Test kernels only: withhold a real TX doorbell, then release the same
 * descriptor to the device. Queue ownership/deadline code stays unchanged. */
static unsigned net_test_stall, net_test_pending;
#endif
static u16 tx_before;      /* the used index before the owner's frame */
static uint64_t net_elapsed(uint64_t since) {
  uint64_t now = hal_mtime();
  return (since && now) ? now - since : 0;
}
static void tx_abandon(void *unused) { /* a killed owner: its frame may be in flight */
  (void)unused;
  __atomic_store_n(&tx_orphan, 1, __ATOMIC_RELEASE);
}
static void tx_take(void) {
  uint64_t t0 = hal_mtime(), parks = 0;
  for (;;) {
    if (__atomic_load_n(&net_offline, __ATOMIC_ACQUIRE))
      fpr_actor_fail("net: the device stalled on an earlier frame -- network offline, send refused");
    unsigned free = 0;
    if (__atomic_compare_exchange_n(&tx_busy, &free, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) break;
    if (__atomic_load_n(&tx_orphan, __ATOMIC_ACQUIRE)) {
      FENCE();
      if (QUSED(&q_tx)->idx != tx_before) { /* the orphan's frame went out */
        q_tx.last_used = QUSED(&q_tx)->idx;
        __atomic_store_n(&tx_orphan, 0, __ATOMIC_RELEASE);
        __atomic_store_n(&tx_busy, 0, __ATOMIC_RELEASE);
        continue;
      }
      if (t0 ? net_elapsed(t0) >= NET_DEADLINE_TICKS : parks >= NET_DEADLINE_PARKS) {
        __atomic_store_n(&net_offline, 1, __ATOMIC_RELEASE);
        fpr_actor_fail("net: the device stalled on an abandoned frame -- network offline");
      }
    } else if (t0 ? net_elapsed(t0) >= 3 * NET_DEADLINE_TICKS : parks >= 3 * NET_DEADLINE_PARKS) {
      fpr_actor_fail("net: waited three deadlines for the transmit buffer -- send refused");
    }
    parks++;
    fpr_actor_sleep_us(200);
  }
  fpr_actor_cleanup_set(tx_abandon, &tx_busy);
}
static void tx_release(void) {
  fpr_actor_cleanup_clear(&tx_busy);
  __atomic_store_n(&tx_busy, 0, __ATOMIC_RELEASE);
}

/* send one frame already assembled at tx_buf+vhdr_len, length flen; the
 * caller owns tx_buf (tx_take) */
static void nic_tx(u32 flen) {
  nset(tx_buf, 0, vhdr_len);              /* virtio-net hdr: no offloads */
  volatile vq_desc_t *d = &QDESC(&q_tx)[0];
  d->addr = (u64)(uintptr_t)tx_buf;
  d->len = vhdr_len + flen;
  d->flags = 0;
  d->next = 0;
  volatile vq_avail_t *av = QAVAIL(&q_tx);
  u16 before = QUSED(&q_tx)->idx;
  tx_before = before;
  av->ring[q_tx.avail_shadow % QSZ] = 0;
  FENCE();
  av->idx = ++q_tx.avail_shadow;
  FENCE();
#ifdef QOS_NET_TEST
  if (__atomic_exchange_n(&net_test_stall, 0, __ATOMIC_ACQ_REL))
    __atomic_store_n(&net_test_pending, 1, __ATOMIC_RELEASE);
  else
#endif
  wr(R_QNOTIFY, 1);
  for (u32 spin = 0; spin < 2000; spin++) {   /* the usual case: done at once */
    FENCE();
    if (QUSED(&q_tx)->idx != before) goto done;
  }
  {
    uint64_t start = hal_mtime(), parks = 0;
    for (;;) {
      FENCE();
      if (QUSED(&q_tx)->idx != before) break;
      if (start ? net_elapsed(start) >= NET_DEADLINE_TICKS : ++parks >= NET_DEADLINE_PARKS) {
        __atomic_store_n(&net_offline, 1, __ATOMIC_RELEASE);
        fpr_actor_cleanup_clear(&tx_busy); /* the buffer stays taken for good */
        fpr_actor_fail("net: transmit timed out (the device stalled) -- network offline");
      }
      fpr_actor_sleep_us(200);
    }
  }
done:
  q_tx.last_used = QUSED(&q_tx)->idx;
}

#if __riscv_xlen != 64
/* ---- transport: ARP + IPv4 + one-connection TCP ------------------------ */
static const u8 our_ip[4] = {10, 0, 2, 15};
static u8 gw_mac[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff}; /* learned from ARP/traffic */

#define ETH_ARP 0x0806
#define ETH_IP4 0x0800
#define TCP_FIN 0x01
#define TCP_SYN 0x02
#define TCP_RST 0x04
#define TCP_PSH 0x08
#define TCP_ACK 0x10

#define RXRING 16384
#define NETCONN 4
typedef struct {
  int est;                 /* 0 free, 1 established */
  u8  pmac[6];
  u8  pip[4];
  u16 pport;
  u32 rcv_nxt, snd_nxt;
  int peer_fin;
  u8  rx[RXRING];
  u32 rxlen;
} conn_t;
static conn_t conns[NETCONN];    /* v6: a small table, not one slot */
static u32 conn_rr;              /* fair-poll rotation cursor */

static conn_t *conn_find(const u8 *pip, u16 sport) {
  for (int i = 0; i < NETCONN; i++)
    if (conns[i].est && conns[i].pport == sport && neq(conns[i].pip, pip, 4))
      return &conns[i];
  return 0;
}
static conn_t *conn_alloc(void) {
  for (int i = 0; i < NETCONN; i++)
    if (!conns[i].est) return &conns[i];
  return 0;                      /* table full: the SYN goes unanswered */
}

static u16 csum16(const u8 *p, u32 n, u32 seed) {
  u32 s = seed;
  while (n > 1) { s += (u32)(p[0] << 8 | p[1]); p += 2; n -= 2; }
  if (n) s += (u32)(p[0] << 8);
  while (s >> 16) s = (s & 0xffff) + (s >> 16);
  return (u16)~s;
}

/* frame scratch layout inside tx_buf: [vhdr][eth 14][ip 20][tcp 20][payload] */
static void tcp_send(conn_t *cn, u8 flags, const u8 *payload, u32 plen) {
  tx_take();
  u8 *eth = tx_buf + vhdr_len;
  u8 *ip = eth + 14, *tcp = ip + 20;
  ncpy(eth, cn->pmac, 6);
  ncpy(eth + 6, our_mac, 6);
  eth[12] = ETH_IP4 >> 8; eth[13] = ETH_IP4 & 0xff;

  u32 iplen = 40 + plen;
  ip[0] = 0x45; ip[1] = 0;
  ip[2] = iplen >> 8; ip[3] = iplen & 0xff;
  ip[4] = 0; ip[5] = 0; ip[6] = 0x40; ip[7] = 0;   /* DF, no frag */
  ip[8] = 64; ip[9] = 6;                            /* TTL, TCP */
  ip[10] = 0; ip[11] = 0;
  ncpy(ip + 12, our_ip, 4);
  ncpy(ip + 16, cn->pip, 4);
  u16 ic = csum16(ip, 20, 0);
  ip[10] = ic >> 8; ip[11] = ic & 0xff;

  tcp[0] = 0; tcp[1] = 80;                          /* src port 80 */
  tcp[2] = cn->pport >> 8; tcp[3] = cn->pport & 0xff;
  u32 seq = cn->snd_nxt, ack = cn->rcv_nxt;
  tcp[4] = seq >> 24; tcp[5] = seq >> 16; tcp[6] = seq >> 8; tcp[7] = seq;
  tcp[8] = ack >> 24; tcp[9] = ack >> 16; tcp[10] = ack >> 8; tcp[11] = ack;
  tcp[12] = 0x50;                                   /* 20-byte header */
  tcp[13] = flags | TCP_ACK;
  tcp[14] = 8192 >> 8; tcp[15] = 8192 & 0xff;       /* window */
  tcp[16] = 0; tcp[17] = 0; tcp[18] = 0; tcp[19] = 0;
  if (plen) ncpy(tcp + 20, payload, plen);

  /* pseudo header: src ip, dst ip, 0, proto, tcp len; then TCP hdr+payload */
  u32 s = 0;
  s += (u32)(our_ip[0] << 8 | our_ip[1]); s += (u32)(our_ip[2] << 8 | our_ip[3]);
  s += (u32)(cn->pip[0] << 8 | cn->pip[1]); s += (u32)(cn->pip[2] << 8 | cn->pip[3]);
  s += 6; s += 20 + plen;
  {
    const u8 *p = tcp; u32 n = 20 + plen;
    while (n > 1) { s += (u32)(p[0] << 8 | p[1]); p += 2; n -= 2; }
    if (n) s += (u32)(p[0] << 8);
  }
  while (s >> 16) s = (s & 0xffff) + (s >> 16);
  u16 tc = (u16)~s;
  if (tc == 0) tc = 0xffff;
  tcp[16] = tc >> 8; tcp[17] = tc & 0xff;

  nic_tx(14 + iplen);
  tx_release();
  cn->snd_nxt += plen;
  if (flags & (TCP_SYN | TCP_FIN)) cn->snd_nxt += 1;
}

static void handle_arp(const u8 *f, u32 len) {
  if (len < 42) return;
  const u8 *arp = f + 14;
  if (arp[6] != 0 || arp[7] != 1) return;           /* request only */
  if (!neq(arp + 24, our_ip, 4)) return;            /* for us? */
  /* learn requester (the slirp gateway) */
  ncpy(gw_mac, arp + 8, 6);
  tx_take();
  u8 *eth = tx_buf + vhdr_len;
  u8 *r = eth + 14;
  ncpy(eth, arp + 8, 6);
  ncpy(eth + 6, our_mac, 6);
  eth[12] = ETH_ARP >> 8; eth[13] = ETH_ARP & 0xff;
  r[0] = 0; r[1] = 1; r[2] = 8; r[3] = 0; r[4] = 6; r[5] = 4;
  r[6] = 0; r[7] = 2;                               /* reply */
  ncpy(r + 8, our_mac, 6);
  ncpy(r + 14, our_ip, 4);
  ncpy(r + 18, arp + 8, 6);
  ncpy(r + 24, arp + 14, 4);
  nic_tx(42);
  tx_release();
}

static void handle_tcp(const u8 *f, u32 len) {
  const u8 *ip = f + 14;
  u32 ihl = (ip[0] & 0xf) * 4;
  u32 iplen = (u32)(ip[2] << 8 | ip[3]);
  if (iplen > len - 14) return;
  const u8 *tcp = ip + ihl;
  u32 thl = (tcp[12] >> 4) * 4;
  const u8 *payload = tcp + thl;
  u32 plen = iplen - ihl - thl;
  u16 dport = (u16)(tcp[2] << 8 | tcp[3]);
  u16 sport = (u16)(tcp[0] << 8 | tcp[1]);
  u32 seq = (u32)tcp[4] << 24 | (u32)tcp[5] << 16 | (u32)tcp[6] << 8 | tcp[7];
  u8 flags = tcp[13];
  if (dport != 80) return;

  conn_t *cn = conn_find(ip + 12, sport);
  if (flags & TCP_RST) { if (cn) cn->est = 0; return; }

  if ((flags & TCP_SYN) && !cn) {
    cn = conn_alloc();
    if (!cn) return;             /* table full: peer retries its SYN */
    cn->est = 1;
    ncpy(cn->pmac, f + 6, 6);
    ncpy(cn->pip, ip + 12, 4);
    cn->pport = sport;
    cn->rcv_nxt = seq + 1;
    cn->snd_nxt = 0x00010000;
    cn->rxlen = 0;
    cn->peer_fin = 0;
    tcp_send(cn, TCP_SYN, 0, 0);                    /* SYN|ACK */
    return;
  }
  if (!cn) return;

  if (seq == cn->rcv_nxt) {
    if (plen) {
      u32 room = RXRING - cn->rxlen;
      u32 take = plen > room ? room : plen;
      ncpy(cn->rx + cn->rxlen, payload, take);
      cn->rxlen += take;
      cn->rcv_nxt += plen;                          /* ack all; overflow drops */
    }
    if (flags & TCP_FIN) { cn->rcv_nxt += 1; cn->peer_fin = 1; }
    if (plen || (flags & TCP_FIN)) tcp_send(cn, 0, 0, 0);
  } else if (plen || (flags & TCP_FIN)) {
    tcp_send(cn, 0, 0, 0);                          /* dup ACK at rcv_nxt */
  }
}


static void net_pump(void) {
  if (!nic) return;
  volatile vq_used_t *u = QUSED(&q_rx);
  FENCE();
  while (q_rx.last_used != u->idx) {
    vq_uelem_t e = u->ring[q_rx.last_used % QSZ];
    q_rx.last_used++;
    u32 id = e.id;
    if (id < QSZ && e.len > (u32)vhdr_len) {
      const u8 *f = rx_bufs[id] + vhdr_len;
      u32 flen = e.len - vhdr_len;
      if (flen >= 14) {
        u16 et = (u16)(f[12] << 8 | f[13]);
        if (et == ETH_ARP) handle_arp(f, flen);
        else if (et == ETH_IP4 && flen >= 34 && f[23] == 6 && neq(f + 30, our_ip, 4))
          handle_tcp(f, flen);
      }
    }
    if (id < QSZ) rx_post(id);
    FENCE();
  }
  wr(R_INTACK, 3);
}

/* v6: the arg is the CONNECTION ID.  netPoll 0 -> the next id with
 * buffered rx (fair rotation) or 0; read/write/close address the id. */
static conn_t *conn_of(V d) {
  if (!ISINT(d)) return 0;
  sw id = UNTAG(d);
  if (id < 1 || id > NETCONN) return 0;
  conn_t *cn = &conns[id - 1];
  return cn->est ? cn : 0;
}

static V h_netPoll(V d) {
  (void)d;
  net_pump();
  for (u32 k = 0; k < NETCONN; k++) {
    u32 i = (conn_rr + k) % NETCONN;
    if (conns[i].est && conns[i].rxlen) {
      conn_rr = i + 1;
      return TAG((sw)i + 1);
    }
  }
  return TAG(0);
}

static V h_netRead(V d) {
  net_pump();
  conn_t *cn = conn_of(d);
  if (!cn) return (V)fpr_mkstr((const u8 *)"", 0);
  u32 n = cn->rxlen > 1024 ? 1024 : cn->rxlen;
  str_t *s = fpr_mkstr(cn->rx, n);
  if (n) {
    ncpy(cn->rx, cn->rx + n, cn->rxlen - n);
    cn->rxlen -= n;
  }
  return (V)s;
}

static V h_netWrite(V d, V sv) {
  if (ISINT(sv) || TID(sv) != T_STR) fpr_cpanic("netWrite: not a String");
  conn_t *cn = conn_of(d);
  if (!cn) return TAG(0);
  str_t *s = (str_t *)sv;
  u64 off = 0;
  while (off < s->len) {
    u32 seg = s->len - off > 1200 ? 1200 : (u32)(s->len - off);
    tcp_send(cn, TCP_PSH, s->bytes + off, seg);
    off += seg;
  }
  return TAG((sw)s->len);
}

static V h_netClose(V d) {
  conn_t *cn = conn_of(d);
  if (cn) {
    tcp_send(cn, TCP_FIN, 0, 0);
    cn->est = 0;
    /* PoC: no TIME_WAIT; slot free immediately. */
  }
  return TAG(0);
}

#else
static V need_actor(void) { fpr_actor_fail("net: use std/net network actor"); return TAG(0); }
static V h_netPoll(V u) { (void)u; return need_actor(); }
static V h_netRead(V u) { (void)u; return need_actor(); }
static V h_netWrite(V a,V b) { (void)a;(void)b; return need_actor(); }
static V h_netClose(V u) { (void)u; return need_actor(); }
#endif
/* ---- device table hook + FPRISC surface ----------------------------------- */
void net_setup(void) {
  static int done;
  if (done) return;
  done = 1;
  if (!net_probe()) nputs("[net] no virtio-net device found\n");
}

FPR_FN(fpr_g_netPoll, h_netPoll, 1);
FPR_FN(fpr_g_netRead, h_netRead, 1);
FPR_FN(fpr_g_netWrite, h_netWrite, 2);
FPR_FN(fpr_g_netClose, h_netClose, 1);

#ifdef QOS_NET_TEST
static V h_netTestStall(V u) {
  (void)u; __atomic_store_n(&net_test_stall, 1, __ATOMIC_RELEASE); return TAG(0);
}
static V h_netTestPending(V u) {
  (void)u; return TAG(__atomic_load_n(&net_test_pending, __ATOMIC_ACQUIRE));
}
static V h_netTestRelease(V u) {
  (void)u;
  if (!__atomic_exchange_n(&net_test_pending, 0, __ATOMIC_ACQ_REL))
    fpr_actor_fail("net test: no withheld descriptor");
  wr(R_QNOTIFY, 1);
  return TAG(0);
}
static V h_netTestNow(V u) { (void)u; return TAG((sw)hal_mtime()); }
static V h_netTestSend(V u) {
  (void)u;
  net_setup();
  if (!nic) fpr_actor_fail("net test: NIC absent");
  tx_take();
  nset(tx_buf + vhdr_len, 0, 60);
  nset(tx_buf + vhdr_len, 0xff, 6);
  ncpy(tx_buf + vhdr_len + 6, our_mac, 6);
  tx_buf[vhdr_len + 12] = 0x88; tx_buf[vhdr_len + 13] = 0xb5;
  nic_tx(60);
  tx_release();
  return TAG(1);
}
FPR_FN(fpr_g_netTestStall, h_netTestStall, 1);
FPR_FN(fpr_g_netTestPending, h_netTestPending, 1);
FPR_FN(fpr_g_netTestRelease, h_netTestRelease, 1);
FPR_FN(fpr_g_netTestNow, h_netTestNow, 1);
FPR_FN(fpr_g_netTestSend, h_netTestSend, 1);
#endif

#if __riscv_xlen == 64
/* Frame-only HAL: copy RX before reposting; TX copies into reserved DMA. */
extern void qos_net_require_owner(void);
static V h_netFrameMode(V u) { (void)u; qos_net_require_owner(); net_setup(); if (!nic) fpr_actor_fail("net: NIC absent"); return TAG(1); }
static V h_netMac(V u) { (void)u; qos_net_require_owner(); return (V)fpr_mkstr(our_mac,6); }
static V h_netRxFrame(V u) {
  (void)u; qos_net_require_owner(); FENCE();
  volatile vq_used_t *used=QUSED(&q_rx);
  if (q_rx.last_used==used->idx) return (V)fpr_mkstr((const u8 *)"",0);
  vq_uelem_t e=used->ring[q_rx.last_used++ % QSZ];
  V out=(V)fpr_mkstr((const u8 *)"",0);
  if (e.id<QSZ) {
    if (e.len>(u32)vhdr_len && e.len<=sizeof(rx_bufs[0]))
      out=(V)fpr_mkstr(rx_bufs[e.id]+vhdr_len,e.len-vhdr_len);
    rx_post(e.id); FENCE();
  }
  return out;
}
static V h_netTxFrame(V bytes) {
  qos_net_require_owner();
  if (ISINT(bytes) || TID(bytes)!=T_STR) fpr_actor_fail("net: frame requires bytes");
  str_t *s=(str_t *)bytes;
  if (s->len<14 || s->len>FRAMESZ) fpr_actor_fail("net: frame length out of range");
  tx_take(); ncpy(tx_buf+vhdr_len,s->bytes,s->len); nic_tx(s->len); tx_release(); return TAG(0);
}
static V h_netKick(V u) { (void)u; qos_net_require_owner(); wr(R_INTACK,3); FENCE_IO();return TAG(0); }
FPR_FN(fpr_g_netFrameMode,h_netFrameMode,1);
FPR_FN(fpr_g_netMac,h_netMac,1);
FPR_FN(fpr_g_netRxFrame,h_netRxFrame,1);
FPR_FN(fpr_g_netTxFrame,h_netTxFrame,1);
FPR_FN(fpr_g_netKick,h_netKick,1);
#endif
