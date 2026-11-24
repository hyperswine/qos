/* qlink_console_flush_check.c -- the console device op (hal/drivers/
 * qlink_dev.c, what UART.qa writes through) must not hold a prompt with no
 * trailing newline until some later receive: UART.qa hands over its whole
 * queue and answers UFlush from an empty queue, so nothing else would carry
 * those bytes. Lines still coalesce: a newline-less tail waits only while a
 * frame is in flight, and the ack sends it; the boot console's byte path
 * (qport_con_write) keeps newline buffering.
 *   cc -O2 -I../../hal/link qlink_console_flush_check.c ../../hal/drivers/qlink_dev.c \
 *      ../../hal/link/qlink_port.c ../../hal/link/qlink.c -o qlink_console_flush_check \
 *      && ./qlink_console_flush_check */
#include "../../hal/drivers/qlink_dev.h"
#include <stdio.h>
#include <string.h>

qport_t qlink_board_port;
static uint32_t clock_ms;

/* the wire: board -> host bytes go straight into the host's parser; host ->
 * board bytes wait in a ring the board's serial rx reads */
static qlink_t host;
static uint8_t to_board[1 << 16];
static size_t tb_head, tb_tail;
static char got[4096];
static size_t got_n;
static uint32_t frames_to_host;

static int b_rx(void *c) { (void)c; return tb_tail == tb_head ? -1 : to_board[tb_tail++ % sizeof to_board]; }
static int b_tx_ready(void *c) { (void)c; return 1; }
static uint8_t b_out[1 << 16];
static size_t b_out_n;
static void b_tx(void *c, uint8_t v) { (void)c; b_out[b_out_n++] = v; }
static uint32_t b_now(void *c) { (void)c; return clock_ms; }

static void h_write(void *c, const uint8_t *b, size_t n) {
  (void)c;
  for (size_t i = 0; i < n; i++) to_board[tb_head++ % sizeof to_board] = b[i];
}
static uint32_t h_now(void *c) { (void)c; return clock_ms; }
static int h_deliver(void *c, uint8_t ch, const uint8_t *p, size_t n) {
  (void)c;
  if (ch == QLINK_CH_CONSOLE) { memcpy(got + got_n, p, n); got_n += n; frames_to_host++; }
  return 0;
}
/* what the board wrote reaches the host; the host acks (on its poll) */
static void host_reads(void) {
  if (b_out_n) { qlink_input(&host, b_out, b_out_n); b_out_n = 0; }
  qlink_poll(&host);
}

static int fails;
#define CHECK(c, what) do { if (!(c)) { printf("FAIL %s (line %d)\n", what, __LINE__); fails++; } } while (0)
static int seen(const char *s) { size_t n = strlen(s); return got_n == n && !memcmp(got, s, n); }

int main(void) {
  qport_serial io = {b_rx, b_tx_ready, b_tx, 0, b_now, 0};
  qport_init(&qlink_board_port, &io);
  qlink_config_t hc = {h_write, h_now, h_deliver, 0, 0, 4, 14, 300};
  qlink_init(&host, &hc);
  qlink_dev_t dev = {&qlink_board_port, 0};
  const qos_console_ops *con = &qlink_console_ops;

  /* the host opens a session */
  const uint8_t hello[6] = {'H', 'E', 'L', 'L', 'O', 7};
  qlink_send_unreliable(&host, QLINK_CH_CONTROL, hello, 6);
  qport_poll(&qlink_board_port);
  host_reads();
  CHECK(qport_session(&qlink_board_port), "session opens");

  /* 1. an idle link: a prompt with no newline reaches the host with no
   *    further board poll (UART.qa has nothing left to write) */
  const char *prompt = "qos> ";
  CHECK(con->write(&dev, (const uint8_t *)prompt, 5) == 5, "prompt taken");
  host_reads();
  CHECK(seen("qos> "), "idle prompt flushed without a newline");

  /* 2. a line then a prompt while that line is unacknowledged: the prompt
   *    coalesces, and the ack (a received byte -> poll) carries it */
  qport_poll(&qlink_board_port); /* take the host's ack for case 1 */
  got_n = 0; frames_to_host = 0;
  CHECK(con->write(&dev, (const uint8_t *)"ls\n", 3) == 3, "line taken");
  CHECK(!qlink_idle(&qlink_board_port.link), "line in flight");
  CHECK(con->write(&dev, (const uint8_t *)"qos> ", 5) == 5, "prompt taken");
  host_reads();
  CHECK(seen("ls\n"), "line sent at once; prompt held while it is in flight");
  uint8_t buf[16];
  (void)con->read(&dev, buf, sizeof buf); /* the receive interrupt's read takes the ack */
  host_reads();
  CHECK(seen("ls\nqos> "), "the ack sends the held prompt");
  CHECK(frames_to_host == 2, "two frames for the line and prompt");

  /* 3. newline batching on the byte path (boot console qcon_putc) */
  qport_poll(&qlink_board_port);
  host_reads();
  qport_poll(&qlink_board_port);
  got_n = 0; frames_to_host = 0;
  const char *msg = "boot: ok\n";
  for (const char *c = msg; *c; c++) qport_con_write(&qlink_board_port, (const uint8_t *)c, 1);
  host_reads();
  CHECK(seen("boot: ok\n") && frames_to_host == 1, "byte writes coalesce into one frame per line");

  puts(fails ? "qlink console flush: FAIL" : "qlink console flush: PASS");
  return fails ? 1 : 0;
}
