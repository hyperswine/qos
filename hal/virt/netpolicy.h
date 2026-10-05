/* Raw RV64 FP-RISC ABI. Sizes/offsets are asserted at the mechanism boundary. */
#ifndef QOS_NETPOLICY_H
#define QOS_NETPOLICY_H
#include <stdint.h>
#define QOS_NET_RXRING 16384
#define QOS_NET_CONNECTIONS 4
typedef struct {
    uint32_t est;
    uint8_t pmac[6], pip[4];
    uint16_t pport;
    uint32_t rcv_nxt, snd_nxt, peer_fin, rxlen;
    uint8_t rx[QOS_NET_RXRING];
} qos_net_conn;
_Static_assert(__builtin_offsetof(qos_net_conn, est) == 0, "netpolicy active offset");
_Static_assert(__builtin_offsetof(qos_net_conn, pmac) == 4, "netpolicy MAC offset");
_Static_assert(__builtin_offsetof(qos_net_conn, pip) == 10, "netpolicy IP offset");
_Static_assert(__builtin_offsetof(qos_net_conn, snd_nxt) == 20, "netpolicy TX sequence offset");
_Static_assert(__builtin_offsetof(qos_net_conn, peer_fin) == 24, "netpolicy FIN offset");
_Static_assert(sizeof(qos_net_conn) == 16416, "netpolicy connection stride");
_Static_assert(__builtin_offsetof(qos_net_conn, rx) == 32, "netpolicy RX offset");
_Static_assert(__builtin_offsetof(qos_net_conn, pport) == 14, "netpolicy port offset");
_Static_assert(__builtin_offsetof(qos_net_conn, rcv_nxt) == 16, "netpolicy sequence offset");
_Static_assert(__builtin_offsetof(qos_net_conn, rxlen) == 28, "netpolicy length offset");
extern long qos_net_receive(const void *frame, long length, const void *mac, void *table, void *reply);
extern long qos_net_emit(void *connection, long flags, const void *payload, long length, const void *mac, void *out);
extern long qos_net_poll(void *table, long cursor, long attempt);
extern long qos_net_read_size(void *connection);
extern void qos_net_consume(void *connection, long length);
extern void *qos_net_connection(void *table, long id);
extern void qos_net_close(void *connection);
extern long qos_net_segment(long remaining);
#endif
