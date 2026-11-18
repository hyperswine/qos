/* qlink_port.h -- a board's end of qlink (qlink.h) over any byte-serial
 * device, carrying the channels the device classes ride on
 * (hal/drivers/qlink_dev.c): console, input, clock, host files, audio.
 *
 * A port is polled: every call pumps it (drains the serial receive side,
 * parses frames, resends, acks). Interrupts only wake whoever then calls it.
 *
 * Sessions. A host opens one with an unreliable control "HELLO" + nonce; the
 * board answers "HELLO" + nonce, and repeats of the same nonce do not reset
 * twice. A session ends on the host's "BYE", or when the host stops
 * acknowledging for QPORT_PEER_LOST_MS while frames are in flight. Without a
 * session the port sends no reliable frames and drops console output: a
 * host that closes and reopens the Tang Nano's UART while the FPGA
 * transmits wedges its BL616 bridge (simple-risc boards/tangnano20k/README.md,
 * "Known issue"), so the board must be quiet whenever a host may reopen.
 *
 * Flow control: a reliable frame the port has no room for is refused (not
 * acknowledged) and the host resends it, so the fixed rings below never drop
 * input. The receive byte ring can lose bytes only if the port is not polled
 * while a host floods it; a lost byte fails its frame's CRC and the frame is
 * resent.
 *
 * Channel messages (host-to-board frames carry at most 14 bytes, so every
 * multi-byte message is reassembled from the channel's ordered stream):
 *   console  bytes, both ways
 *   input    host -> board: events of 4 bytes [kind, code lo, code hi, value]
 *            (kind 1 = key; value 1 down, 0 up, 2 repeat; evdev key codes)
 *   clock    host -> board: one frame, the host's epoch milliseconds in ASCII
 *            decimal (sent after HELLO and every minute)
 *   files    board -> host: [id][op][plen lo,hi][path][dlen lo,hi][data]
 *            host -> board: [id][status][len lo,hi][data]  (status 0 ok,
 *            1 error: data is the message). Ops in QPORT_F_*.
 *   audio    board -> host: [kind][...]; kind 1 = tone [freq lo,hi][ms lo,hi]
 */
#ifndef QOS_QLINK_PORT_H
#define QOS_QLINK_PORT_H
#include <stdint.h>
#include "qlink.h"

#define QPORT_PEER_LOST_MS 1500u
#define QPORT_REPLY_MS 5000u /* a host file request with no answer by then fails */

enum { QPORT_F_READ = 1, QPORT_F_WRITE = 2, QPORT_F_APPEND = 3, QPORT_F_LIST = 4 };

typedef struct qport_serial {
  int (*rx)(void *ctx);                 /* a received byte, or -1 */
  int (*tx_ready)(void *ctx);           /* room for one more byte now */
  void (*tx)(void *ctx, uint8_t byte);
  void (*arm)(void *ctx, int rx);       /* receive interrupt on/off, or NULL */
  uint32_t (*now_ms)(void *ctx);
  void *ctx;
} qport_serial;

#define QPORT_RX_RING 1024u
#define QPORT_CON_IN 512u
#define QPORT_CON_OUT 200u
#define QPORT_IN_RING 1024u

typedef struct qport {
  qport_serial io;
  qlink_t link;
  int ready;
  uint8_t session; /* host nonce, 0 = none */
  uint32_t heard_at, frames_seen;
  uint8_t rx[QPORT_RX_RING];
  uint32_t rx_head, rx_tail;
  /* console */
  uint8_t con_in[QPORT_CON_IN];
  uint32_t con_in_head, con_in_tail;
  uint8_t con_out[QPORT_CON_OUT];
  uint32_t con_out_n;
  /* input events */
  uint8_t in[QPORT_IN_RING];
  uint32_t in_head, in_tail;
  /* clock: the host's epoch at clock_at (local ms) */
  uint64_t clock_epoch;
  uint32_t clock_at;
  int clock_known;
  /* files: the one request in flight */
  uint8_t file_id;
  uint8_t file_hdr[4];
  uint32_t file_hdr_n, file_len, file_got;
  uint8_t *file_buf;
  uint32_t file_max;
  int file_state; /* 0 idle, 1 waiting, 2 answered */
  uint8_t file_status;
} qport_t;

void qport_init(qport_t *p, const qport_serial *io);
void qport_poll(qport_t *p);
int qport_session(const qport_t *p);

/* Send a whole message on a reliable channel, split into frames, waiting for
 * window room. 0 sent, -1 no session (or it ended while waiting). */
int qport_send(qport_t *p, uint8_t ch, const uint8_t *msg, uint32_t n);

/* console: write takes what fits without waiting (all of it with no session:
 * dropped); flush sends the line buffer, waiting for window room. */
uint32_t qport_con_write(qport_t *p, const uint8_t *b, uint32_t n);
void qport_con_flush(qport_t *p);
uint32_t qport_con_read(qport_t *p, uint8_t *dst, uint32_t max);
int qport_drain(qport_t *p, uint32_t ms); /* flush, then wait for acks up to ms */

uint32_t qport_in_read(qport_t *p, uint8_t *dst, uint32_t max); /* whole events */
/* the host's epoch milliseconds now, in ASCII decimal; 0 when unknown */
uint32_t qport_clock(qport_t *p, char *dst, uint32_t max);
/* One file request. reply receives up to max bytes; *len its length.
 * 0 ok, 1 the host refused (reply holds why), -1 no session, -2 no answer
 * within QPORT_REPLY_MS, -3 the answer was longer than max. */
int qport_file(qport_t *p, uint8_t op, const uint8_t *path, uint32_t plen, const uint8_t *data,
               uint32_t dlen, uint8_t *reply, uint32_t max, uint32_t *len);
#endif
