/* Actor binding and boxed/raw memory conversions, no protocol policy. The
 * fixed arena has image lifetime, including after actor failure. Only the
 * installed actor may access it; no automatic restart/reuse after TX failure. */
#include "fpr.h"
extern V fpr_g_myself_call1(V);
static uw qos_net_owner;
#if defined(__riscv)
extern V qos_process_net_owner(void) __attribute__((weak));
#endif
V qos_net_owner_value(void) {
#if defined(__riscv)
  if (fpr_sched && qos_process_net_owner) return qos_process_net_owner();
#endif
  uw owner=__atomic_load_n(&qos_net_owner,__ATOMIC_ACQUIRE);
  return owner ? (V)owner : TAG(0);
}
static int qos_net_is_owner(void) {
  V owner=qos_net_owner_value();
  return !ISINT(owner) && fpr_g_myself_call1(TAG(0)) == owner;
}
void qos_net_require_owner(void) {
  if (!qos_net_is_owner()) fpr_actor_fail("net: frame/state access requires network owner");
}
static V h_netOwner(V u) { (void)u; return qos_net_owner_value(); }
static V h_netBindOwner(V actor) {
  if (fpr_sched) return h_netOwner(TAG(0)); /* processes use the kernel owner */
  if (ISINT(actor) || TID(actor)!=T_ACTOR) fpr_actor_fail("net: binding requires actor");
  uw expected=0;
  __atomic_compare_exchange_n(&qos_net_owner,&expected,(uw)actor,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
  return h_netOwner(TAG(0));
}
FPR_FN(fpr_g_netOwner,h_netOwner,1);
FPR_FN(fpr_g_netBindOwner,h_netBindOwner,1);
#if __riscv_xlen == 64
#include "virt/netpolicy.h"
static qos_net_conn qos_net_arena[QOS_NET_CONNECTIONS];
static void *net_arena(V handle) {
  qos_net_require_owner();
  if (!ISINT(handle) || UNTAG(handle)!=1) fpr_actor_fail("net: invalid protocol arena");
  return qos_net_arena;
}
static str_t *net_bytes(V bytes) {
  if (ISINT(bytes) || TID(bytes)!=T_STR) fpr_actor_fail("net: expected bytes");
  return (str_t *)bytes;
}
static V h_netPolicyState(V u) { (void)u; qos_net_require_owner(); return TAG(1); }
static V h_netPolicyRx(V state,V frame,V mac) {
  str_t *f=net_bytes(frame),*m=net_bytes(mac); uint8_t out[54];
  if (m->len!=6) fpr_actor_fail("net: invalid MAC");
  long n=qos_net_receive(f->bytes,f->len,m->bytes,net_arena(state),out);
  return (V)fpr_mkstr(out,n);
}
static V h_netPolicyPoll(V state,V cursor) { return TAG(qos_net_poll(net_arena(state),UNTAG(cursor),0)); }
static V h_netPolicyRead(V state,V id) {
  qos_net_conn *c=qos_net_connection(net_arena(state),UNTAG(id));
  if (!c) return (V)fpr_mkstr((const uint8_t *)"",0);
  long n=qos_net_read_size(c); V out=(V)fpr_mkstr(c->rx,n); qos_net_consume(c,n); return out;
}
static V h_netPolicyEncode(V state,V id,V bytes,V mac) {
  qos_net_conn *c=qos_net_connection(net_arena(state),UNTAG(id));
  str_t *p=net_bytes(bytes),*m=net_bytes(mac);uint8_t out[1254];
  if (p->len>1200 || m->len!=6) fpr_actor_fail("net: invalid encode buffers");
  if (!c) return (V)fpr_mkstr((const uint8_t *)"",0);
  long n=qos_net_emit(c,8,p->bytes,p->len,m->bytes,out);return (V)fpr_mkstr(out,n);
}
static V h_netPolicyClose(V state,V id,V mac) {
  qos_net_conn *c=qos_net_connection(net_arena(state),UNTAG(id)); str_t *m=net_bytes(mac);uint8_t out[54];
  if (m->len!=6) fpr_actor_fail("net: invalid MAC");
  if (!c) return (V)fpr_mkstr((const uint8_t *)"",0);
  long n=qos_net_emit(c,1,0,0,m->bytes,out);qos_net_close(c);return (V)fpr_mkstr(out,n);
}
static V h_netPolicySegment(V n) { return TAG(qos_net_segment(UNTAG(n))); }
#else
static V no_frames(void) { fpr_actor_fail("net: Ethernet frames unavailable on this transport");return TAG(0); }
static V h_netFrameMode(V u) { (void)u; return TAG(0); }
static V h_netRxFrame(V u) { (void)u; return no_frames(); }
static V h_netTxFrame(V bytes) { (void)bytes; return no_frames(); }
static V h_netKick(V u) { (void)u; return no_frames(); }
static V h_netMac(V u) { (void)u; return no_frames(); }
FPR_FN(fpr_g_netFrameMode,h_netFrameMode,1);
FPR_FN(fpr_g_netRxFrame,h_netRxFrame,1);
FPR_FN(fpr_g_netTxFrame,h_netTxFrame,1);
FPR_FN(fpr_g_netKick,h_netKick,1);
FPR_FN(fpr_g_netMac,h_netMac,1);
static V h_netPolicyState(V u) { (void)u;return no_frames(); }
static V h_netPolicyRx(V a,V b,V c) { (void)a;(void)b;(void)c;return no_frames(); }
static V h_netPolicyPoll(V a,V b) { (void)a;(void)b;return no_frames(); }
static V h_netPolicyRead(V a,V b) { (void)a;(void)b;return no_frames(); }
static V h_netPolicyEncode(V a,V b,V c,V d) { (void)a;(void)b;(void)c;(void)d;return no_frames(); }
static V h_netPolicyClose(V a,V b,V c) { (void)a;(void)b;(void)c;return no_frames(); }
static V h_netPolicySegment(V n) { (void)n;return no_frames(); }
#endif
FPR_FN(fpr_g_netPolicyState,h_netPolicyState,1);
FPR_FN(fpr_g_netPolicyRx,h_netPolicyRx,3);
FPR_FN(fpr_g_netPolicyPoll,h_netPolicyPoll,2);
FPR_FN(fpr_g_netPolicyRead,h_netPolicyRead,2);
FPR_FN(fpr_g_netPolicyEncode,h_netPolicyEncode,4);
FPR_FN(fpr_g_netPolicyClose,h_netPolicyClose,3);
FPR_FN(fpr_g_netPolicySegment,h_netPolicySegment,1);
