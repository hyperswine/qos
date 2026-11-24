/* qlink_dev.c -- console, input, clock, host files and audio over a qlink
 * port: each op is a call into hal/link/qlink_port.c on the instance's port. */
#include "qlink_dev.h"

static qport_t *port(void *st) {
  qlink_dev_t *d = st;
  if (!d->port->ready && d->init) d->init();
  return d->port;
}

static void con_open(void *st) { qport_poll(port(st)); }
/* UART.qa hands over its whole queue (and has nothing left that a later
 * write would carry), so the tail after the last newline goes out now too */
static uint32_t con_write(void *st, const uint8_t *p, uint32_t n) { return qport_con_write_all(port(st), p, n); }
static uint32_t con_read(void *st, uint8_t *dst, uint32_t max) { return qport_con_read(port(st), dst, max); }
static void con_arm(void *st, int rx, int tx) {
  /* acknowledgements arrive as received bytes, so transmit progress needs
   * the receive interrupt too */
  qport_t *p = port(st);
  if (p->io.arm) p->io.arm(p->io.ctx, rx || tx);
}
const qos_console_ops qlink_console_ops = {QOS_CONSOLE_OPS_VERSION, con_open, con_write, con_read, con_arm, 0};

static uint32_t in_read(void *st, uint8_t *dst, uint32_t max) { return qport_in_read(port(st), dst, max); }
const qos_input_ops qlink_input_ops = {QOS_INPUT_OPS_VERSION, in_read};

static uint32_t clk_now(void *st, char *dst, uint32_t max) { return qport_clock(port(st), dst, max); }
const qos_clock_ops qlink_clock_ops = {QOS_CLOCK_OPS_VERSION, clk_now};

static int hf_call(void *st, uint8_t op, const uint8_t *path, uint32_t plen, const uint8_t *data, uint32_t dlen,
                   uint8_t *reply, uint32_t max, uint32_t *len) {
  return qport_file(port(st), op, path, plen, data, dlen, reply, max, len);
}
const qos_hostfs_ops qlink_hostfs_ops = {QOS_HOSTFS_OPS_VERSION, hf_call};

static int aud_tone(void *st, uint32_t freq, uint32_t ms) {
  uint8_t m[5] = {1, (uint8_t)freq, (uint8_t)(freq >> 8), (uint8_t)ms, (uint8_t)(ms >> 8)};
  if (freq > 0xffff || ms > 0xffff) return -1;
  return qport_send(port(st), QLINK_CH_AUDIO, m, sizeof m);
}
const qos_audio_ops qlink_audio_ops = {QOS_AUDIO_OPS_VERSION, aud_tone};
