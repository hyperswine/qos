/* net_raw.c -- the raw hosted device tier (see net_raw.h).  This is
 * net.c's I/O logic verbatim, minus every fpr.h type: the extraction
 * exists so qosp (runtime/portable) and posix.bin share ONE socket and
 * pseudo-bus implementation instead of drifting copies. */
#include "net_raw.h"
#include "hostlog.h"

#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/socket.h>
#include <unistd.h>

#define RXCAP 8192
#define MAXCONN QOS_NET_MAXCONN

static int lfd = -1;
static struct nconn {
  int fd; /* -1 = free slot */
  uint8_t rx[RXCAP];
  uint32_t rxlen;
  int eof; /* peer closed: reported ONCE as an empty read, then dropped */
  char *tx;           /* unsent tail (malloc'd on first need), FIFO */
  uint32_t txlen, txcap;
} conns[MAXCONN];
static int conns_init;
static uint32_t poll_rr; /* fair-poll rotation cursor */

static void conns_setup(void) {
  if (conns_init) return;
  conns_init = 1;
  for (int i = 0; i < MAXCONN; i++) conns[i].fd = -1;
}
static struct nconn *conn_of(int64_t id) {
  if (id < 1 || id > MAXCONN) return 0;
  struct nconn *c = &conns[id - 1];
  return c->fd >= 0 ? c : 0;
}
static int net_trace = -1; /* QOS_NET_TRACE=1: every accept, EOF, and drop on stderr */
static void net_log(const char *what, struct nconn *c, int extra) {
  if (net_trace < 0) net_trace = getenv("QOS_NET_TRACE") ? 1 : 0;
  if (net_trace) fprintf(stderr, "net: %s slot %d fd %d rx %u eof %d tx %u x %d\n", what,
                         (int)(c - conns) + 1, c->fd, c->rxlen, c->eof, c->txlen, extra);
}
static void conn_drop(struct nconn *c) {
  net_log("drop", c, 0);
  close(c->fd);
  c->fd = -1;
  c->rxlen = 0;
  c->eof = 0;
  free(c->tx);
  c->tx = 0;
  c->txlen = c->txcap = 0;
}
/* push the unsent tail; a write error means the peer is gone */
static void tx_flush(struct nconn *c) {
  while (c->txlen && !c->eof) {
    ssize_t n = write(c->fd, c->tx, c->txlen);
    if (n > 0) {
      memmove(c->tx, c->tx + n, c->txlen - (uint32_t)n);
      c->txlen -= (uint32_t)n;
      continue;
    }
    if (n < 0 && (errno == EAGAIN || errno == EINTR)) return;
    c->eof = 1;
    c->rxlen = 0;
    return;
  }
}

void qos_netraw_setup(void) {
  if (lfd >= 0) return;
  int port = 8000;
  const char *p = getenv("FPR_PORT");
  if (p && *p) port = atoi(p);
  lfd = socket(AF_INET, SOCK_STREAM, 0);
  if (lfd < 0) { qos_hostlog("net: socket"); exit(2); }
  int one = 1;
  setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  struct sockaddr_in a;
  memset(&a, 0, sizeof a);
  a.sin_family = AF_INET;
  a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  a.sin_port = htons((uint16_t)port);
  /* restarting a server across TIME_WAIT is normal, not an error */
  setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  if (bind(lfd, (struct sockaddr *)&a, sizeof a)) {
    qos_hostlog("net: bind (port busy?)");
    exit(2);
  }
  if (listen(lfd, 128)) { qos_hostlog("net: listen"); exit(2); }
  fcntl(lfd, F_SETFL, O_NONBLOCK);
}

static void net_pump(void) {
  if (lfd < 0) return;
  conns_setup();
  /* accept as many waiting peers as free slots allow; a full table
   * leaves the rest in the listen backlog */
  for (;;) {
    int slot = -1;
    for (int i = 0; i < MAXCONN; i++)
      if (conns[i].fd < 0) { slot = i; break; }
    if (slot < 0) break;
    int fd = accept(lfd, 0, 0);
    if (fd < 0) break; /* EAGAIN: nobody there */
    fcntl(fd, F_SETFL, O_NONBLOCK);
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    conns[slot].fd = fd;
    conns[slot].rxlen = 0;
    conns[slot].eof = 0;
    net_log("accept", &conns[slot], 0);
  }
  for (int i = 0; i < MAXCONN; i++) {
    struct nconn *c = &conns[i];
    if (c->fd < 0) continue;
    tx_flush(c);
    while (c->rxlen < RXCAP && !c->eof) {
      ssize_t n = read(c->fd, c->rx + c->rxlen, RXCAP - c->rxlen);
      if (n > 0) { c->rxlen += (uint32_t)n; continue; }
      if (n == 0 || (n < 0 && errno != EAGAIN && errno != EINTR)) {
        c->eof = 1;
        net_log("eof", c, n < 0 ? errno : 0);
      } /* peer gone (FIN, or a reset): its bytes are served
                     * first, then netPoll names it once more and netRead
                     * answers with NOTHING -- the program's cue that the
                     * connection id is over */
      break; /* EAGAIN or EOF: serve what we have */
    }
  }
}

int64_t qos_netraw_poll(void) {
  net_pump();
  for (int k = 0; k < MAXCONN; k++) {
    uint32_t i = (poll_rr + k) % MAXCONN;
    if (conns[i].fd >= 0 && (conns[i].rxlen || conns[i].eof)) {
      poll_rr = i + 1; /* rotate: next poll starts past this id */
      return (int64_t)i + 1;
    }
  }
  return 0;
}

int64_t qos_netraw_read(int64_t id, char *dst, uint64_t cap) {
  net_pump();
  struct nconn *c = conn_of(id);
  if (!c) return 0;
  uint32_t n = c->rxlen > cap ? (uint32_t)cap : c->rxlen;
  memcpy(dst, c->rx, n);
  if (n) {
    memmove(c->rx, c->rx + n, c->rxlen - n);
    c->rxlen -= n;
  } else if (c->eof) conn_drop(c); /* the empty read IS the notice; slot freed */
  return (int64_t)n;
}

int64_t qos_netraw_write(int64_t id, const char *src, uint64_t len) {
  struct nconn *c = conn_of(id);
  if (!c || c->eof) return 0; /* a gone peer takes nothing more */
  tx_flush(c);
  uint64_t off = 0;
  if (!c->txlen) { /* nothing queued: the fast path writes straight through */
    while (off < len) {
      ssize_t n = write(c->fd, src + off, len - off);
      if (n > 0) { off += (uint64_t)n; continue; }
      if (n < 0 && (errno == EAGAIN || errno == EINTR)) break; /* queue the rest */
      c->eof = 1; /* peer closed under us: reported through netPoll/netRead
                   * like a FIN, never dropped silently (a silent drop left
                   * the program's record of the id alive for the NEXT peer) */
      c->rxlen = 0;
      return (int64_t)off;
    }
  }
  if (off < len) { /* the kernel is full: keep the tail, never block the hart */
    uint64_t need = c->txlen + (len - off);
    if (need > QOS_NET_TXCAP) { /* a reader this slow is gone to us */
      c->eof = 1;
      c->rxlen = 0;
      return (int64_t)off;
    }
    if (need > c->txcap) {
      uint32_t cap = c->txcap ? c->txcap : 4096;
      while (cap < need) cap *= 2;
      char *t = realloc(c->tx, cap);
      if (!t) { c->eof = 1; c->rxlen = 0; return (int64_t)off; }
      c->tx = t;
      c->txcap = cap;
    }
    memcpy(c->tx + c->txlen, src + off, len - off);
    c->txlen = (uint32_t)need;
  }
  return (int64_t)len;
}

int64_t qos_netraw_close(int64_t id) {
  struct nconn *c = conn_of(id);
  if (c) { net_log("close-by-program", c, 0); conn_drop(c); }
  return 0;
}

/* ---- the register tier: a 16550-ish uart over stdio ----------------
 * (net.c's model, moved whole: LSR always reports THR empty; DR
 * follows a nonblocking stdin peek; mtime is 10MHz-ish ticks from
 * CLOCK_MONOTONIC at virt's offset.) */
#define CLINT_MTIME (QOS_CLINT_BASE + 49144) /* virt's mtime offset, honored */
#define UART_THR (QOS_UART_BASE + 0)
#define UART_RBR (QOS_UART_BASE + 0)
#define UART_IER (QOS_UART_BASE + 1)
#define UART_FCR (QOS_UART_BASE + 2)
#define UART_LCR (QOS_UART_BASE + 3)
#define UART_LSR (QOS_UART_BASE + 5)
#define UART_SCR (QOS_UART_BASE + 7)

static int stdin_pending = -1;
static uint8_t uart_lcr, uart_scr;
static uint8_t uart_ier, uart_dll, uart_dlm;

static void stdin_peek(void) {
  if (stdin_pending >= 0) return;
  int fl = fcntl(0, F_GETFL);
  fcntl(0, F_SETFL, fl | O_NONBLOCK);
  uint8_t b;
  if (read(0, &b, 1) == 1) stdin_pending = b;
  fcntl(0, F_SETFL, fl);
}

int qos_mmioraw_read(uint64_t addr, uint64_t *out) {
  switch (addr) {
    case UART_LCR:
      *out = uart_lcr;
      return 0;
    case UART_IER:
      *out = uart_ier;
      return 0;
    case UART_LSR: {
      stdin_peek();
      *out = 0x20u | (stdin_pending >= 0 ? 0x01u : 0u); /* THRE | DR */
      return 0;
    }
    case UART_SCR:
      *out = uart_scr;
      return 0;
    case CLINT_MTIME: {
      struct timespec ts;
      clock_gettime(CLOCK_MONOTONIC, &ts);
      *out = (uint64_t)ts.tv_sec * 10000000u + (uint64_t)ts.tv_nsec / 100u;
      return 0;
    }
    case UART_RBR: {
      stdin_peek();
      if (stdin_pending < 0) { *out = 0; return 0; }
      *out = (uint64_t)stdin_pending;
      stdin_pending = -1;
      return 0;
    }
    default:
      return -1;
  }
}

int qos_mmioraw_write(uint64_t addr, uint64_t v) {
  switch (addr) {
    case UART_THR: {
      if (uart_lcr & 0x80) { uart_dll = (uint8_t)v; return 0; } /* DLAB: DLL */
      qos_console_putc((char)v); /* bounded wait, never holds the hart: hostlog.h */
      return 0;
    }
    /* the interrupt-era registers, modeled honestly for a host with
     * no interrupts: IER is stored (the uart service actor sets RDA/
     * THRE; nothing fires -- the portable tier is its synchronous
     * backend), FCR is accepted and ignored, and DLAB routes the
     * divisor latches (UART.qa's params round trip must not leak
     * divisor bytes into stdout). */
    case UART_IER:
      if (uart_lcr & 0x80) { uart_dlm = (uint8_t)v; return 0; } /* DLAB: DLM */
      uart_ier = (uint8_t)v;
      return 0;
    case UART_FCR:
      return 0;
    case UART_LCR:
      uart_lcr = (uint8_t)v;
      return 0;
    case UART_SCR:
      uart_scr = (uint8_t)v;
      return 0;
    default:
      return -1;
  }
}

/* ---- device discovery: the same table shape as virt hal.c ----------- */
typedef struct {
  const char *name;
  uint64_t base;
  void (*setup)(void);
} rawdev_t;

void qos_blkraw_setup(void); /* blk_raw.h -- linked wherever this table is */

static rawdev_t rawdevs[] = {
    {"uart", QOS_UART_BASE, 0},
    {"clint", QOS_CLINT_BASE, 0},
    {"net", 0, qos_netraw_setup},
    {"blk", 0, qos_blkraw_setup},
};
#define NRAWDEVS (sizeof(rawdevs) / sizeof(rawdevs[0]))

int qos_devraw_lookup(const char *name, uint64_t len, uint64_t *base) {
  for (size_t i = 0; i < NRAWDEVS; i++) {
    const char *n = rawdevs[i].name;
    size_t j = 0;
    for (; j < len && n[j] && n[j] == name[j]; j++) {}
    if (j == len && n[j] == '\0') {
      if (rawdevs[i].setup) rawdevs[i].setup();
      *base = rawdevs[i].base;
      return 1;
    }
  }
  return 0;
}
