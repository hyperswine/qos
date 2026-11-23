/* qlink.c -- the qlink frame codec and session (qlink.h). */
#include "qlink.h"

static uint16_t crc16_step(uint16_t crc, const uint8_t *p, size_t n) {
  static const uint16_t tbl[16] = {
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7,
    0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef,
  };
  while (n--) {
    uint8_t b = *p++;
    crc = (uint16_t)((crc << 4) ^ tbl[((crc >> 12) ^ (b >> 4)) & 0x0f]);
    crc = (uint16_t)((crc << 4) ^ tbl[((crc >> 12) ^ b) & 0x0f]);
  }
  return crc;
}

uint16_t qlink_crc16(const uint8_t *p, size_t n) {
  return crc16_step(0xffff, p, n);
}

static size_t put(uint8_t *out, size_t i, uint8_t b) {
  if (b == 0x7e || b == 0x7d || b == 0x03) { out[i++] = 0x7d; out[i++] = (uint8_t)(b ^ 0x20); }
  else out[i++] = b;
  return i;
}

size_t qlink_encode(uint8_t ch, uint8_t seq, uint8_t ack, const uint8_t *payload, size_t n, uint8_t *out) {
  uint8_t head[4] = {ch, seq, ack, (uint8_t)n};
  size_t i = 0;
  out[i++] = 0x7e;
  for (int k = 0; k < 4; k++) i = put(out, i, head[k]);
  for (size_t k = 0; k < n; k++) i = put(out, i, payload[k]);
  /* stream crc over head then payload with no temporary buffer copy */
  uint16_t crc = crc16_step(0xffff, head, 4);
  if (n) crc = crc16_step(crc, payload, n);
  i = put(out, i, (uint8_t)(crc >> 8));
  i = put(out, i, (uint8_t)crc);
  out[i++] = 0x7e;
  return i;
}

void qlink_init(qlink_t *q, const qlink_config_t *cfg) {
  uint8_t *p = (uint8_t *)q;
  for (size_t i = 0; i < sizeof *q; i++) p[i] = 0;
  q->cfg = *cfg;
  if (!q->cfg.window || q->cfg.window > QLINK_WINDOW_MAX) q->cfg.window = QLINK_WINDOW_MAX;
  if (!q->cfg.payload_max || q->cfg.payload_max > QLINK_PAYLOAD_MAX) q->cfg.payload_max = QLINK_PAYLOAD_MAX;
  if (!q->cfg.rto_ms) q->cfg.rto_ms = 250;
  q->expect_seq = 0;
}

void qlink_reset(qlink_t *q) {
  q->next_seq = q->base_seq = q->in_flight = 0;
  q->expect_seq = 0;
  q->ack_owed = 0;
}

static uint8_t last_in_order(const qlink_t *q) { return (uint8_t)(q->expect_seq - 1); }

static void emit(qlink_t *q, uint8_t ch, uint8_t seq, const uint8_t *payload, size_t n) {
  uint8_t out[2 * (QLINK_PAYLOAD_MAX + 6) + 2];
  size_t len = qlink_encode(ch, seq, last_in_order(q), payload, n, out);
  q->cfg.write(q->cfg.ctx, out, len);
  q->ack_owed = 0;
  q->stats.frames_out++;
}

int qlink_send(qlink_t *q, uint8_t ch, const uint8_t *payload, size_t n) {
  if (n > q->cfg.payload_max) return -2;
  if (q->in_flight >= q->cfg.window) return -1;
  uint8_t slot = (uint8_t)(q->next_seq % QLINK_WINDOW_MAX);
  q->pending[slot].ch = (uint8_t)(ch & 0x3f);
  q->pending[slot].len = (uint8_t)n;
  for (size_t i = 0; i < n; i++) q->pending[slot].data[i] = payload[i];
  if (!q->in_flight) q->sent_at = q->cfg.now_ms(q->cfg.ctx);
  q->in_flight++;
  emit(q, q->pending[slot].ch, q->next_seq, payload, n);
  q->next_seq++;
  return 0;
}

int qlink_send_unreliable(qlink_t *q, uint8_t ch, const uint8_t *payload, size_t n) {
  if (n > q->cfg.payload_max) return -2;
  emit(q, (uint8_t)((ch & 0x3f) | QLINK_UNRELIABLE), 0, payload, n);
  return 0;
}

/* The peer has every frame up to and including `ack`. */
static void acked(qlink_t *q, uint8_t ack) {
  uint8_t done = (uint8_t)(ack - q->base_seq + 1); /* frames newly covered */
  if (!q->in_flight || done == 0 || done > q->in_flight) return;
  q->base_seq = (uint8_t)(q->base_seq + done);
  q->in_flight = (uint8_t)(q->in_flight - done);
  q->sent_at = q->cfg.now_ms(q->cfg.ctx);
}

static void frame_done(qlink_t *q) {
  if (q->flen < 6) { q->stats.crc_errors++; return; }
  uint8_t ch = q->frame[0], seq = q->frame[1], ack = q->frame[2], n = q->frame[3];
  if ((size_t)n + 6 != q->flen) { q->stats.crc_errors++; return; }
  uint16_t crc = (uint16_t)((q->frame[4 + n] << 8) | q->frame[5 + n]);
  if (qlink_crc16(q->frame, (size_t)n + 4) != crc) { q->stats.crc_errors++; return; }
  q->stats.frames_in++;
  q->peer_heard = 1;
  acked(q, ack);
  if (ch & QLINK_ACK_ONLY) return;
  if (ch & QLINK_UNRELIABLE) { (void)q->cfg.deliver(q->cfg.ctx, (uint8_t)(ch & 0x3f), q->frame + 4, n); return; }
  if (seq != q->expect_seq) { q->stats.dup_frames++; q->ack_owed = 1; return; }
  if (q->cfg.deliver(q->cfg.ctx, (uint8_t)(ch & 0x3f), q->frame + 4, n) < 0) { q->stats.refused++; return; }
  q->expect_seq++;
  q->ack_owed = 1;
}

void qlink_input(qlink_t *q, const uint8_t *bytes, size_t n) {
  for (size_t i = 0; i < n; i++) {
    uint8_t b = bytes[i];
    if (b == 0x7e) {
      if (q->in_frame && q->flen) frame_done(q);
      q->in_frame = 1; q->flen = 0; q->escaped = 0;
      continue;
    }
    if (!q->in_frame) { if (q->cfg.raw) q->cfg.raw(q->cfg.ctx, b); continue; }
    if (b == 0x7d) { q->escaped = 1; continue; }
    if (q->escaped) { b ^= 0x20; q->escaped = 0; }
    if (q->flen >= sizeof q->frame) { q->stats.overlong++; q->in_frame = 0; q->flen = 0; continue; }
    q->frame[q->flen++] = b;
  }
}

void qlink_poll(qlink_t *q) {
  if (q->in_flight && q->cfg.now_ms(q->cfg.ctx) - q->sent_at >= q->cfg.rto_ms) {
    for (uint8_t k = 0; k < q->in_flight; k++) {
      uint8_t seq = (uint8_t)(q->base_seq + k), slot = (uint8_t)(seq % QLINK_WINDOW_MAX);
      emit(q, q->pending[slot].ch, seq, q->pending[slot].data, q->pending[slot].len);
      q->stats.resent++;
    }
    q->sent_at = q->cfg.now_ms(q->cfg.ctx);
  }
  if (q->ack_owed) emit(q, QLINK_ACK_ONLY, 0, 0, 0);
}
