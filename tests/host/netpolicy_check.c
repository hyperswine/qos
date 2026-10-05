#include "fpr.h"
#include "../../hal/virt/netpolicy.h"
#include <string.h>
static int bytes_equal(const void *a, const void *b, unsigned n) {
  const uint8_t *x=a,*y=b; for(unsigned i=0;i<n;i++) if(x[i]!=y[i])return 0; return 1;
}
#define CHECK(x) do { if (!(x)) return TAG(__LINE__); } while (0)
static qos_net_conn table[4];
static uint8_t frame[2048], output[2048];
static const uint8_t mac[6] = {2,3,4,5,6,7}, peer[6] = {8,9,10,11,12,13};
static const uint8_t ip[4] = {10,0,2,2}, ours[4] = {10,0,2,15};
static unsigned get16(const uint8_t *p) { return p[0]*256 + p[1]; }
static uint32_t get32(const uint8_t *p) { return (uint32_t)get16(p)<<16 | get16(p+2); }
static void put16(uint8_t *p, unsigned n) { p[0]=n>>8; p[1]=n; }
static void put32(uint8_t *p, uint32_t n) { put16(p,n>>16); put16(p+2,n); }
static unsigned checksum(const uint8_t *p, unsigned n, unsigned s) {
  for (; n>1; n-=2,p+=2) s+=get16(p);
  if(n) s+=*p<<8;
  while(s>>16) s=(s&65535)+(s>>16);
  return (~s)&65535;
}
static void fix(unsigned n) {
  uint8_t *p=frame+14, *t=p+20;
  put16(p+10,0); put16(p+10,checksum(p,20,0));
  put16(t+16,0); put16(t+16,checksum(t,n-34,get16(p+12)+get16(p+14)+get16(p+16)+get16(p+18)+6+n-34));
}
static unsigned packet(unsigned port, uint32_t seq, unsigned flags, unsigned n) {
  memset(frame,0,sizeof(frame));
  memcpy(frame,mac,6); memcpy(frame+6,peer,6); put16(frame+12,0x800);
  uint8_t *p=frame+14,*t=p+20;
  p[0]=0x45; put16(p+2,40+n); p[8]=64;p[9]=6;
  memcpy(p+12,ip,4);memcpy(p+16,ours,4);
  put16(t,port);put16(t+2,80);put32(t+4,seq);put32(t+8,65537);
  t[12]=0x50;t[13]=flags;put16(t+14,8192);
  for(unsigned i=0;i<n;i++)t[20+i]=(i*13)&255;
  fix(54+n);return 54+n;
}
static unsigned receive(unsigned n) { memset(output,0xa5,sizeof(output)); return qos_net_receive(frame,n,mac,table,output); }
static int valid(unsigned n) {
  return n>=54 && checksum(output+14,20,0)==0 &&
    checksum(output+34,n-34,get16(output+26)+get16(output+28)+get16(output+30)+get16(output+32)+6+n-34)==0;
}
static V check(V ignored) {
  (void)ignored;
  /* Every truncated frame and corrupt header leaves table and output intact. */
  packet(1234,100,2,0);
  for(unsigned n=0;n<54;n++) { CHECK(receive(n)==0); CHECK(table[0].est==0); CHECK(output[0]==0xa5); }
  unsigned offsets[]={14,16,20,23,30,46,50};
  for(unsigned i=0;i<sizeof(offsets)/sizeof(*offsets);i++) {
    packet(1234,100,2,0);frame[offsets[i]]^=0xff;
    CHECK(receive(54)==0);CHECK(table[0].est==0);
  }
  packet(1234,100,2,0);frame[14]=0x44;fix(54);CHECK(receive(54)==0);
  packet(1234,100,2,0);frame[46]=0x40;fix(54);CHECK(receive(54)==0);
  packet(1234,100,2,0);frame[46]=0xf0;fix(54);CHECK(receive(54)==0);
  packet(1234,100,2,0);put16(frame+20,0x2000);fix(54);CHECK(receive(54)==0);
  packet(1234,100,2,0);put16(frame+20,1);fix(54);CHECK(receive(54)==0);
  packet(1234,100,2,0);put16(frame+36,81);fix(54);CHECK(receive(54)==0);
  /* ARP uses byte-exact Ethernet/IPv4 reply fields, no connection mutation. */
  memset(frame,0,sizeof(frame));put16(frame+12,0x806);put16(frame+14,1);put16(frame+16,0x800);
  frame[18]=6;frame[19]=4;put16(frame+20,1);memcpy(frame+22,peer,6);memcpy(frame+28,ip,4);memcpy(frame+38,ours,4);
  CHECK(receive(41)==0);CHECK(receive(42)==42);
  uint8_t want[42]={0};memcpy(want,peer,6);memcpy(want+6,mac,6);put16(want+12,0x806);
  memcpy(want+14,frame+14,8);put16(want+20,2);memcpy(want+22,mac,6);memcpy(want+28,ours,4);memcpy(want+32,peer,6);memcpy(want+38,ip,4);
  CHECK(bytes_equal(output,want,42));CHECK(output[42]==0xa5);
  for(unsigned i=14;i<=21;i++) { unsigned old=frame[i];frame[i]^=0xff;CHECK(receive(42)==0);frame[i]=old; }
  frame[41]=16;CHECK(receive(42)==0);
  /* SYN, odd binary payload, duplicate ACK, partial receive, FIN and RST. */
  packet(1234,100,2,0);CHECK(receive(54)==54);CHECK(valid(54));
  CHECK(output[47]==18);CHECK(get32(output+38)==65536);CHECK(get32(output+42)==101);
  CHECK(table[0].rcv_nxt==101 && table[0].snd_nxt==65537 && table[0].rxlen==0);
  packet(1234,101,0x18,17);CHECK(receive(71)==54);CHECK(valid(54));
  CHECK(table[0].rxlen==17 && table[0].rcv_nxt==118);CHECK(bytes_equal(table[0].rx,frame+54,17));
  packet(1234,101,0x18,17);CHECK(receive(71)==54);CHECK(table[0].rxlen==17 && get32(output+42)==118);
  table[0].rxlen=16380;
  packet(1234,118,0x19,17);CHECK(receive(71)==54);
  CHECK(table[0].rxlen==16384 && table[0].rcv_nxt==122 && table[0].peer_fin==0);
  CHECK(get16(output+48)==0); /* never ACK dropped bytes or FIN after them */
  CHECK(qos_net_read_size(&table[0])==1024);qos_net_consume(&table[0],1024);
  CHECK(table[0].rxlen==15360);packet(1234,122,0x19,13);CHECK(receive(67)==54);
  CHECK(table[0].rcv_nxt==136 && table[0].peer_fin==1);
  packet(1234,135,4,0);CHECK(receive(54)==0 && table[0].est==1);
  packet(1234,136,4,0);CHECK(receive(54)==0 && table[0].est==0);
  /* Four slots, refusal, fair rotation, reset reuse and wrapping sequence. */
  memset(table,0,sizeof(table));
  for(unsigned i=0;i<4;i++) {packet(2000+i,0xffffffff,2,0);CHECK(receive(54)==54);CHECK(table[i].rcv_nxt==0);}
  packet(2004,200,2,0);CHECK(receive(54)==0);
  for(unsigned i=0;i<4;i++) {packet(2000+i,0,0x18,1);CHECK(receive(55)==54);}
  for(unsigned i=0;i<8;i++) CHECK(qos_net_poll(table,i,0)==(long)(i%4+1));
  CHECK(qos_net_connection(table,0)==0 && qos_net_connection(table,5)==0);
  CHECK(qos_net_connection(table,1)==&table[0]);qos_net_close(&table[0]);
  CHECK(qos_net_connection(table,1)==0);table[0].est=1;
  uint8_t data[1200];for(unsigned i=0;i<1200;i++)data[i]=i;
  table[0].snd_nxt=0xfffffffe;
  CHECK(qos_net_emit(&table[0],8,data,1200,mac,output)==1254);CHECK(valid(1254));
  CHECK(bytes_equal(output+54,data,1200) && table[0].snd_nxt==1198);
  CHECK(qos_net_segment(1201)==1200 && qos_net_segment(0)==0 && qos_net_segment(17)==17);
  return TAG(0);
}
FPR_FN(fpr_g_netPolicyCheck, check, 1);
