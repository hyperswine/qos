/* nonet.c -- a board with no network interface (Spectre boards).
 *
 * QOS's network service (std/net.fpr) starts by asking netFrameMode, and on
 * QEMU virt without a NIC the virtio driver answers by failing the asking
 * actor with "net: NIC absent"; System.qa then reports the network offline
 * and carries on. Here every net primitive gives that same answer, so a
 * board without a NIC boots the same way instead of panicking on a missing
 * device. `device "net"` names this entry (a plain device, no class).
 * hal/net_actor_bridge.c (linked beside it) owns the network-owner and
 * frame primitives; on RV32 it reports frames unavailable. */
#include "fpr.h"

#define ABSENT1(sym) static V sym##_h(V a) { (void)a; fpr_actor_fail("net: NIC absent"); return 0; } FPR_FN(fpr_g_##sym, sym##_h, 1);
#define ABSENT2(sym) static V sym##_h(V a, V b) { (void)a; (void)b; fpr_actor_fail("net: NIC absent"); return 0; } FPR_FN(fpr_g_##sym, sym##_h, 2);
#define ABSENT3(sym) static V sym##_h(V a, V b, V c) { (void)a; (void)b; (void)c; fpr_actor_fail("net: NIC absent"); return 0; } FPR_FN(fpr_g_##sym, sym##_h, 3);

ABSENT1(netPoll)
ABSENT1(netRead)
ABSENT2(netWrite)
ABSENT1(netClose)

void nonet_setup(void) {}
