/* qlink_port.c -- see qlink_port.h. */
#include "qlink_port.h"

static uint32_t now(const qport_t *p) { return p->io.now_ms(p->io.ctx); }

static void rx_pull(qport_t *p) {
  int b;
  while ((b = p->io.rx(p->io.ctx)) >= 0)
    if (p->rx_head - p->rx_tail < QPORT_RX_RING) p->rx[p->rx_head++ % QPORT_RX_RING] = (uint8_t)b;
}

/* qlink's raw writer. The receive side is drained while waiting to transmit:
 * a window of resends is about 1 KB, and a 32-byte receive FIFO would
 * overflow meanwhile. Parsing waits for the next poll (qlink_input cannot
 * run inside a send). */
static void wire(void *ctx, const uint8_t *b, size_t n) {
  qport_t *p = ctx;
  for (size_t i = 0; i < n; i++) {
    while (!p->io.tx_ready(p->io.ctx)) rx_pull(p);
    p->io.tx(p->io.ctx, b[i]);
    rx_pull(p);
  }
}
static uint32_t link_now(void *ctx) { return now(ctx); }

static void backlog_put(qport_t *p, const uint8_t *b, uint32_t n) {
  for (uint32_t i = 0; i < n; i++) {
    p->backlog[p->backlog_head++ % QPORT_BACKLOG] = b[i];
    if (p->backlog_n < QPORT_BACKLOG) p->backlog_n++;
    else p->backlog_dropped++;
  }
}
/* send the backlog as the window allows: a dropped-bytes note first */
static void replay_some(qport_t *p) {
  while (p->replay && qlink_can_send(&p->link)) {
    uint8_t chunk[QLINK_PAYLOAD_MAX];
    uint32_t k = 0;
    if (p->backlog_dropped) {
      static const char note[] = "[qlink: ";
      for (const char *c = note; *c; c++) chunk[k++] = (uint8_t)*c;
      char digits[12]; uint32_t d = 0, v = p->backlog_dropped;
      do { digits[d++] = (char)('0' + v % 10); v /= 10; } while (v);
      while (d) chunk[k++] = (uint8_t)digits[--d];
      static const char tail[] = " earlier bytes of output dropped]\n";
      for (const char *c = tail; *c; c++) chunk[k++] = (uint8_t)*c;
      p->backlog_dropped = 0;
    } else {
      uint32_t start = p->backlog_head - p->backlog_n;
      while (k < QLINK_PAYLOAD_MAX && p->backlog_n) { chunk[k++] = p->backlog[start++ % QPORT_BACKLOG]; p->backlog_n--; }
    }
    if (k) qlink_send(&p->link, QLINK_CH_CONSOLE, chunk, k);
    if (!p->backlog_n && !p->backlog_dropped) p->replay = 0;
  }
}

static void session_end(qport_t *p) {
  qlink_reset(&p->link);
  p->session = 0;
  backlog_put(p, p->con_out, p->con_out_n); /* not yet sent: the next host sees it */
  p->con_out_n = 0;
  if (p->file_state == 1) p->file_state = 0; /* qport_file sees no session */
}

static void file_bytes(qport_t *p, const uint8_t *b, uint32_t n) {
  for (uint32_t i = 0; i < n; i++) {
    if (p->file_hdr_n < 4) {
      p->file_hdr[p->file_hdr_n++] = b[i];
      if (p->file_hdr_n == 4) {
        p->file_len = (uint32_t)p->file_hdr[2] | (uint32_t)p->file_hdr[3] << 8;
        p->file_got = 0;
      }
    } else {
      if (p->file_state == 1 && p->file_hdr[0] == p->file_id && p->file_got < p->file_max) p->file_buf[p->file_got] = b[i];
      p->file_got++;
    }
    if (p->file_hdr_n == 4 && p->file_got == p->file_len) {
      if (p->file_state == 1 && p->file_hdr[0] == p->file_id) {
        p->file_status = p->file_hdr[1];
        p->file_state = 2;
      }
      p->file_hdr_n = 0;
    }
  }
}

static void clock_frame(qport_t *p, const uint8_t *b, size_t n) {
  uint64_t v = 0;
  if (!n) return;
  for (size_t i = 0; i < n; i++) {
    if (b[i] < '0' || b[i] > '9') return;
    v = v * 10 + (uint64_t)(b[i] - '0');
  }
  p->clock_epoch = v;
  p->clock_at = now(p);
  p->clock_known = 1;
}

static int deliver(void *ctx, uint8_t ch, const uint8_t *b, size_t n) {
  qport_t *p = ctx;
  if (ch == QLINK_CH_CONTROL) {
    if ((n == 5 || n == 6) && b[0] == 'H' && b[1] == 'E' && b[2] == 'L' && b[3] == 'L' && b[4] == 'O') {
      /* the host repeats one nonce until answered: only a new nonce resets */
      if (n == 5 || b[5] != p->session || !p->session) {
        session_end(p);
        p->session = n == 6 && b[5] ? b[5] : 1;
        p->file_hdr_n = 0;
        p->replay = p->backlog_n || p->backlog_dropped;
      }
      p->heard_at = now(p);
      uint8_t answer[6] = {'H', 'E', 'L', 'L', 'O', p->session};
      qlink_send_unreliable(&p->link, QLINK_CH_CONTROL, answer, n);
    } else if (n == 3 && b[0] == 'B' && b[1] == 'Y' && b[2] == 'E') {
      session_end(p);
    }
    return 0;
  }
  if (!p->session) return 0;
  /* a frame that does not fit is refused whole, and the host resends it once
   * the reader has made room: nothing is dropped */
  if (ch == QLINK_CH_CONSOLE) {
    if (QPORT_CON_IN - (p->con_in_head - p->con_in_tail) < n) return -1;
    for (size_t i = 0; i < n; i++) p->con_in[p->con_in_head++ % QPORT_CON_IN] = b[i];
  } else if (ch == QLINK_CH_INPUT) {
    if (QPORT_IN_RING - (p->in_head - p->in_tail) < n) return -1;
    for (size_t i = 0; i + 4 <= n; i += 4)
      for (int k = 0; k < 4; k++) p->in[p->in_head++ % QPORT_IN_RING] = b[i + k];
  } else if (ch == QLINK_CH_CLOCK) {
    clock_frame(p, b, n);
  } else if (ch == QLINK_CH_FILES) {
    file_bytes(p, b, (uint32_t)n);
  }
  return 0;
}

void qport_init(qport_t *p, const qport_serial *io) {
  uint8_t *z = (uint8_t *)p;
  for (uint32_t i = 0; i < sizeof *p; i++) z[i] = 0;
  p->io = *io;
  qlink_config_t cfg = {wire, link_now, deliver, 0, p, 4, 255, 300};
  qlink_init(&p->link, &cfg);
  p->ready = 1;
}

int qport_session(const qport_t *p) { return p->ready && p->session; }

static void qport_poll_rx(qport_t *p) {
  if (!p->ready) return;
  rx_pull(p);
  while (p->rx_tail != p->rx_head) {
    uint8_t b[64];
    size_t n = 0;
    while (p->rx_tail != p->rx_head && n < sizeof b) b[n++] = p->rx[p->rx_tail++ % QPORT_RX_RING];
    qlink_input(&p->link, b, n);
    rx_pull(p);
  }
  if (p->link.stats.frames_in != p->frames_seen) { p->frames_seen = p->link.stats.frames_in; p->heard_at = now(p); }
  if (p->session && p->link.in_flight && now(p) - p->heard_at > QPORT_PEER_LOST_MS) session_end(p);
  if (!p->session) return;
  qlink_poll(&p->link);
  replay_some(p);
}

void qport_poll(qport_t *p) {
  qport_poll_rx(p);
  if (!p->ready || !p->session) return;
  /* console bytes waiting in the line buffer go out as soon as the window
   * allows: an interrupt-driven writer (UART.qa) may have nothing more to
   * write, so no later write would carry them. The backlog goes first. */
  if (!p->replay && p->con_out_n && qlink_can_send(&p->link)) {
    qlink_send(&p->link, QLINK_CH_CONSOLE, p->con_out, p->con_out_n);
    p->con_out_n = 0;
  }
}

int qport_send(qport_t *p, uint8_t ch, const uint8_t *msg, uint32_t n) {
  uint8_t s = p->session;
  while (n) {
    while (p->session == s && s && !qlink_can_send(&p->link)) qport_poll(p);
    if (!s || p->session != s) return -1;
    uint32_t k = n > QLINK_PAYLOAD_MAX ? QLINK_PAYLOAD_MAX : n;
    qlink_send(&p->link, ch, msg, k);
    msg += k;
    n -= k;
  }
  return 0;
}

void qport_con_flush(qport_t *p) {
  if (!p->con_out_n) return;
  if (!p->session) { backlog_put(p, p->con_out, p->con_out_n); p->con_out_n = 0; return; }
  uint8_t s = p->session;
  while (p->session == s && (p->replay || !qlink_can_send(&p->link))) qport_poll_rx(p);
  if (p->session != s || !p->con_out_n) { p->con_out_n = 0; return; }
  qlink_send(&p->link, QLINK_CH_CONSOLE, p->con_out, p->con_out_n);
  p->con_out_n = 0;
}

uint32_t qport_con_write(qport_t *p, const uint8_t *b, uint32_t n) {
  qport_poll_rx(p);
  if (!p->session) { backlog_put(p, b, n); return n; } /* nobody is listening: kept for the next host */
  uint32_t took = 0;
  int has_nl = 0;
  while (took < n) {
    if (p->con_out_n == QPORT_CON_OUT) {
      if (p->replay || !qlink_can_send(&p->link)) break; /* the window is full: the caller retries */
      qport_con_flush(p);
    }
    uint8_t c = b[took++];
    p->con_out[p->con_out_n++] = c;
    if (c == '\n') has_nl = 1;
  }
  /* Coalesce small writes into p->con_out; flush immediately on newline (or
   * full buffer above), while prompt lines without '\n' flush on the next
   * qport_poll / qport_con_read / qport_drain. */
  if (has_nl && p->con_out_n && !p->replay && qlink_can_send(&p->link)) qport_con_flush(p);
  return took;
}

uint32_t qport_con_read(qport_t *p, uint8_t *dst, uint32_t max) {
  qport_poll(p);
  uint32_t i = 0;
  while (i < max && p->con_in_tail != p->con_in_head) dst[i++] = p->con_in[p->con_in_tail++ % QPORT_CON_IN];
  return i;
}

int qport_drain(qport_t *p, uint32_t ms) {
  qport_con_flush(p);
  uint32_t t0 = now(p);
  while (p->session && !qlink_idle(&p->link) && now(p) - t0 < ms) qport_poll(p);
  return qlink_idle(&p->link);
}

uint32_t qport_in_read(qport_t *p, uint8_t *dst, uint32_t max) {
  qport_poll(p);
  uint32_t i = 0;
  while (i + 4 <= max && p->in_head - p->in_tail >= 4)
    for (int k = 0; k < 4; k++) dst[i++] = p->in[p->in_tail++ % QPORT_IN_RING];
  return i;
}

uint32_t qport_clock(qport_t *p, char *dst, uint32_t max) {
  qport_poll(p);
  if (!p->clock_known || max < 21) return 0;
  uint64_t v = p->clock_epoch + (uint64_t)(now(p) - p->clock_at);
  char tmp[21];
  uint32_t n = 0;
  do { tmp[n++] = (char)('0' + v % 10); v /= 10; } while (v);
  for (uint32_t i = 0; i < n; i++) dst[i] = tmp[n - 1 - i];
  return n;
}

int qport_file(qport_t *p, uint8_t op, const uint8_t *path, uint32_t plen, const uint8_t *data,
               uint32_t dlen, uint8_t *reply, uint32_t max, uint32_t *len) {
  *len = 0;
  qport_poll(p);
  if (!p->session) return -1;
  if (plen > 0xffff || dlen > 0xffff) return 1;
  uint8_t s = p->session;
  p->file_id++;
  p->file_buf = reply;
  p->file_max = max;
  p->file_state = 1;
  uint8_t head[4] = {p->file_id, op, (uint8_t)plen, (uint8_t)(plen >> 8)};
  uint8_t dl[2] = {(uint8_t)dlen, (uint8_t)(dlen >> 8)};
  /* one message, split into frames: header, path, data length, data */
  uint8_t frame[QLINK_PAYLOAD_MAX];
  uint32_t fill = 0, total = 4 + plen + 2 + dlen;
  for (uint32_t i = 0; i < total; i++) {
    uint8_t b = i < 4 ? head[i] : i < 4 + plen ? path[i - 4] : i < 6 + plen ? dl[i - 4 - plen] : data[i - 6 - plen];
    frame[fill++] = b;
    if (fill == QLINK_PAYLOAD_MAX || i + 1 == total) {
      if (qport_send(p, QLINK_CH_FILES, frame, fill)) { p->file_state = 0; return -1; }
      fill = 0;
    }
  }
  uint32_t t0 = now(p);
  while (p->file_state == 1 && p->session == s && now(p) - t0 < QPORT_REPLY_MS) qport_poll(p);
  if (p->session != s) { p->file_state = 0; return -1; }
  if (p->file_state != 2) { p->file_state = 0; return -2; }
  p->file_state = 0;
  if (p->file_got > max) { *len = max; return -3; }
  *len = p->file_got;
  return p->file_status ? 1 : 0;
}
