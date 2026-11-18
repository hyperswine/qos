/* qlink_sruart.h -- qlink over Simple-Risc's UART (TX 0x10000000, STATUS +4
 * bit0 TX ready / bit1 RX waiting, RX +8), with a console channel: what a
 * board image prints goes out in console frames, keys come back from the
 * host program (tools/qhost). Polled: the host sends one small frame and
 * waits for its ack, so the 32-byte receive FIFO never overruns. */
#ifndef QOS_QLINK_SRUART_H
#define QOS_QLINK_SRUART_H
#include <stdint.h>
#include "qlink_port.h"
extern qport_t qlink_board_port; /* the board's one link; qlink_dev instances name it */
void qcon_init(uint32_t (*now_ms)(void));
void qcon_putc(char c);        /* buffered; sent at '\n', when full, or on flush */
int qcon_getc(void);           /* a console byte from the host, or -1 */
void qcon_flush(void);         /* send what is buffered (waits for window room) */
void qcon_poll(void);          /* drain the UART, resend, ack */
int qcon_drain(uint32_t ms);   /* flush and wait until the host acked everything, up to ms */
#endif
