/* qlink.h -- one framed, checked byte stream carrying several channels over a
 * UART (QOS docs/2026-11-18-DEVICE-CLASSES.md; limits measured in
 * docs/2026-11-18-SPECTRE-84-SPIKES.md). The same code runs on the board and
 * on the host (tools/qhost): no allocation, no OS calls.
 *
 * Frame on the wire:  7E | ch | seq | ack | len | payload[len] | crc16 hi lo | 7E
 *   - 7E, 7D and 03 inside a frame are sent as 7D, b ^ 20 (a raw 03 resets
 *     Simple-Risc cores, so it never appears inside a frame).
 *   - crc16 is CRC-16/CCITT-FALSE over ch..payload.
 *   - ch bits 0-5: the channel; bit 6: an ack-only frame (no payload, no
 *     sequence number of its own); bit 7: unreliable (sequenced for order,
 *     never retransmitted: display tiles, log lines).
 *   - seq numbers this side's reliable frames (mod 256); ack is the last
 *     reliable frame received in order from the peer.
 * Sessions: the host opens with an unreliable control frame "HELLO"; the
 * board resets its sequence state (qlink_reset) and answers "HELLO".
 * Reliable frames are go-back-N with a window: unacked frames are resent
 * after rto_ms. Bytes outside frames are handed to `raw` (ROM output, panics).
 *
 * Pacing: a side with tx_chunk > 0 writes a frame in pieces of at most
 * tx_chunk bytes; the host uses that with window 1 and small frames, because
 * the Tang Nano's USB bridge drops board-to-host bytes when one host write
 * is large (24-byte writes are safe). */
#ifndef QOS_QLINK_H
#define QOS_QLINK_H
#include <stddef.h>
#include <stdint.h>

#define QLINK_PAYLOAD_MAX 255u
#define QLINK_WINDOW_MAX 4u

enum {
  QLINK_CH_CONTROL = 0, QLINK_CH_CONSOLE = 1, QLINK_CH_INPUT = 2, QLINK_CH_DISPLAY = 3,
  QLINK_CH_CLOCK = 4, QLINK_CH_FILES = 5, QLINK_CH_AUDIO = 6, QLINK_CH_LOG = 7
};
#define QLINK_ACK_ONLY 0x40u
#define QLINK_UNRELIABLE 0x80u

typedef struct qlink qlink_t;
typedef struct {
  void (*write)(void *ctx, const uint8_t *bytes, size_t n); /* raw bytes to the wire */
  uint32_t (*now_ms)(void *ctx);
  void (*deliver)(void *ctx, uint8_t ch, const uint8_t *payload, size_t n);
  void (*raw)(void *ctx, uint8_t byte);                    /* a byte outside frames, or NULL */
  void *ctx;
  uint8_t window;      /* reliable frames in flight, 1..QLINK_WINDOW_MAX */
  uint8_t payload_max; /* largest payload this side sends */
  uint16_t rto_ms;     /* resend unacked frames after this */
} qlink_config_t;

typedef struct {
  uint32_t frames_in, frames_out, resent, crc_errors, dup_frames, overlong;
} qlink_stats_t;

struct qlink {
  qlink_config_t cfg;
  qlink_stats_t stats;
  /* send side */
  uint8_t next_seq, base_seq, in_flight;
  uint32_t sent_at;
  struct { uint8_t ch, len; uint8_t data[QLINK_PAYLOAD_MAX]; } pending[QLINK_WINDOW_MAX];
  /* receive side */
  uint8_t expect_seq, ack_owed, peer_heard;
  uint8_t frame[QLINK_PAYLOAD_MAX + 8];
  uint16_t flen;
  uint8_t in_frame, escaped;
};

void qlink_init(qlink_t *q, const qlink_config_t *cfg);
/* Start a new session: both sequence spaces back to 0, unacked frames
 * dropped. A host opening the link sends an unreliable control frame
 * "HELLO"; the board calls this and answers "HELLO" (qlink_sruart.c). */
void qlink_reset(qlink_t *q);
/* Queue a reliable frame (0), or -1 when the window is full: call
 * qlink_poll and try again. Payloads longer than payload_max are refused (-2). */
int qlink_send(qlink_t *q, uint8_t ch, const uint8_t *payload, size_t n);
/* Send an unreliable frame now. */
int qlink_send_unreliable(qlink_t *q, uint8_t ch, const uint8_t *payload, size_t n);
/* Feed received wire bytes. */
void qlink_input(qlink_t *q, const uint8_t *bytes, size_t n);
/* Resend after a timeout and send an owed ack; call often. */
void qlink_poll(qlink_t *q);
/* Room for another reliable frame now. */
static inline int qlink_can_send(const qlink_t *q) { return q->in_flight < q->cfg.window; }
/* Everything sent has been acknowledged. */
static inline int qlink_idle(const qlink_t *q) { return q->in_flight == 0; }

uint16_t qlink_crc16(const uint8_t *p, size_t n);
/* Encode one frame into out (room: 2 * (n + 6) + 2); returns its length. */
size_t qlink_encode(uint8_t ch, uint8_t seq, uint8_t ack, const uint8_t *payload, size_t n, uint8_t *out);
#endif
