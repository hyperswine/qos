#include "devtable.h"
#include "fpr.h"
#include "servo.h"
#include "sd.h"
#ifdef SPECTRE_QLINK
/* The console over qlink (hal/link): the host program tools/qhost frames
 * keys and shows output; built with -DSPECTRE_QLINK (SPECTRE_CONSOLE=qlink). */
#include "qlink_sruart.h"
#endif
static void say(const char *s) {
  while (*s)
    hal_putc(*s++);
}
extern uint64_t spectre_raw_ticks(void);
static uint64_t boot_ticks;

#ifdef SPECTRE_QLINK
static uint32_t uptime_ms(void);
#endif
void fpr_builtin_main(void) {

  boot_ticks = spectre_raw_ticks();
#ifdef SPECTRE_QLINK
  qcon_init(uptime_ms);
#endif
  fpr_rt_init();
  fpr_hart_main(0);
}
void hal_putc(char c) {
#ifdef SPECTRE_QLINK
  qcon_putc(c);
  return;
#endif
#ifdef TEST_QEMU
  volatile unsigned char *q = (void *)0x10000000;
  while (!(q[5] & 32))
    ;
  q[0] = c;
  return;
#endif
  volatile unsigned *u = (void *)0x10000000;
  while (!(u[1] & 1))
    ;
  *u = c;
}
void hal_poweroff(int code) {
  (void)code;
  say("END\nDONE");
#ifdef SPECTRE_QLINK
  qcon_drain(2000);
#endif
  for (;;)
    ;
}

// The scheduler uses a 10 MHz timebase; the board CLINT counts CPU clocks.
extern uint64_t spectre_raw_ticks(void);
extern void spectre_raw_arm(uw, uint64_t);
#ifdef TEST_QEMU
#define CORE_MHZ 10
#elif !defined(CORE_MHZ) /* the board build passes -DCORE_MHZ */
#define CORE_MHZ 54
#endif
#ifdef SPECTRE_QLINK
static uint32_t uptime_ms(void) { return (uint32_t)((spectre_raw_ticks() - boot_ticks) / (CORE_MHZ * 1000u)); }
#endif
/* a console byte, or -1: the raw UART, or the host's console frames */
static int con_getc(void) {
#ifdef SPECTRE_QLINK
  return qcon_getc();
#else
  volatile unsigned *u = (void *)0x10000000;
  return (u[1] & 2) ? (int)(u[2] & 255) : -1;
#endif
}
uint64_t hal_mtime(void) {
  uint64_t n = spectre_raw_ticks() - boot_ticks;
  return n / CORE_MHZ * 10 + (n % CORE_MHZ) * 10 / CORE_MHZ;
}
void hal_timer_arm(uw hart, uint64_t delta) {
  spectre_raw_arm(hart,
                  delta / 10 * CORE_MHZ + ((delta % 10) * CORE_MHZ + 9) / 10);
}

/* The device table (the QLog volume on the SD card, hal/drivers/sd_spi.c behind
 * the BLOCK class) is generated from bsp/spectre54 or bsp/spectre84/board.json
 * by tools/board.sol. */
enum { RUNNING=-3, STOPPED=-4, EMPTY=-5 };
typedef struct {
 uint8_t image[4096] __attribute__((aligned(16)));
 volatile int status;
 unsigned polls, yields;
 V actor;
} app_job;
static app_job jobs[2]={{.status=EMPTY},{.status=EMPTY}};
static unsigned latest;
static V prompt(V ignored){
 static int skip_lf;
 char line[1024];
 for(;;){unsigned n=0,bad=0;say("qos> ");
 for(;;){int got;while((got=con_getc())<0){
#ifdef SPECTRE_QLINK
  qcon_flush();
#endif
  if(jobs[0].status==RUNNING || jobs[1].status==RUNNING)fpr_fuel_exhausted();}unsigned c=(unsigned)got;
 if(skip_lf){skip_lf=0;if(c==10)continue;}
 if(c==10||c==13){skip_lf=c==13;hal_putc(10);break;}
 if(c==8||c==127){if(n){n--;say("\b \b");}continue;}
 if(c<32||c>126||n==sizeof(line))bad=1;
 else {line[n++]=c;hal_putc(c);}
 }
 if(!bad && n)return (V)fpr_mkstr((uint8_t*)line,n);
 if(bad)say("invalid or overlength command\n");
 }}
FPR_FN(fpr_g_spectrePrompt,prompt,1);

static int digit(unsigned c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:-1;}
static V job_put(app_job *j,V s){str_t *v=(str_t*)s;uw pos=(uw)s-(uw)j->image;
 if(pos>sizeof(j->image)-sizeof(str_t)||pos%4||v->tid!=T_STR||v->len>sizeof(j->image)-pos-sizeof(str_t))return (V)&fpr_unit;
 for(uw i=0;i<v->len;i++)hal_putc(v->bytes[i]);hal_putc('\n');return (V)&fpr_unit;}
static void poll_job(app_job *j){
 if ((++j->polls & 127)==0){j->yields++;fpr_fuel_exhausted();}
}
static V put_first(V s){return job_put(&jobs[0],s);}
static V put_second(V s){return job_put(&jobs[1],s);}
static void poll_first(void){poll_job(&jobs[0]);}
static void poll_second(void){poll_job(&jobs[1]);}
extern V fpr_g_send_call2(V,V), fpr_g_receive_call1(V), fpr_g_myself_call1(V);

/* The two-slot ABI names the other live job at send time. Only immediate
   integers cross this boundary, so neither image owns the other's data. */
static V send_peer(app_job *peer,V value){
 if(peer->status!=RUNNING || !ISINT(value))return TAG(0);
 return TAG(fpr_sent(fpr_g_send_call2(peer->actor,value)));
}
static V send_from_first(V value){return send_peer(&jobs[1],value);}
static V send_from_second(V value){return send_peer(&jobs[0],value);}
static V receive_int(V unused){
 return fpr_g_receive_call1(fpr_g_myself_call1(TAG(0)));
}
typedef V (*app_entry)(V (*)(V),void (*)(void),V (*)(V),V (*)(V));
static V run_job(app_job *j,V (*put)(V),void (*poll)(void)){
 V v=((app_entry)(uintptr_t)j->image)(put,poll,j==jobs?send_from_first:send_from_second,receive_int);
 j->status=ISINT(v)&&UNTAG(v)>=0&&UNTAG(v)<=255?(int)UNTAG(v):-1;
 return (V)&fpr_unit;
}
static V first_body(V me){return run_job(&jobs[0],put_first,poll_first);}
static V second_body(V me){return run_job(&jobs[1],put_second,poll_second);}
FPR_FN(first_entry,first_body,1);
FPR_FN(second_entry,second_body,1);
extern V fpr_g_spawn_call1(V),fpr_g_kill_call1(V);
static app_job *select_job(V id){
 int n=UNTAG(id);
 return n==0?&jobs[latest]:n==1||n==2?&jobs[n-1]:0;
}
static V job(V id,V op){
 app_job *j=select_job(id);
 if(!j)return TAG(261);
 if(UNTAG(op)==0)return TAG(j->status<0?256-j->status:j->status);
 if(j->status!=RUNNING)return TAG(0);
 fpr_g_kill_call1(j->actor);j->status=STOPPED;return TAG(1);
}
static V ticks(V id){app_job *j=select_job(id);return TAG(j?j->yields&0x3fffffff:0);}
FPR_FN(fpr_g_spectreJob,job,2);
FPR_FN(fpr_g_spectreTicks,ticks,1);
static V app_run(V text){
 unsigned slot=jobs[0].status==RUNNING;
 app_job *j=&jobs[slot];
 if(j->status==RUNNING)return TAG(0);
 str_t *s=(str_t*)text;uint32_t hdr[3]={0},crc=~0u;
 if(s->len<=24 || s->len%2 || s->len>24+sizeof(j->image)*2)return TAG(-1);
 unsigned len=s->len/2-12;
 for(unsigned i=0;i<len+12;i++){int h=digit(s->bytes[2*i]),l=digit(s->bytes[2*i+1]);if(h<0||l<0)return TAG(-1);
 unsigned byte=(h<<4)|l;
 if(i<12){hdr[i/4]|=(uint32_t)byte<<(8*(i%4));continue;}
 j->image[i-12]=byte;crc^=byte;for(int j=0;j<8;j++)crc=(crc>>1)^((0u-(crc&1))&0xedb88320u);}
 if((hdr[0]!=0x31415853u && hdr[0]!=0x32415853u && hdr[0]!=0x33415853u)||hdr[1]!=len||hdr[2]!=~crc||len<4)return TAG(-1);
 // Legacy hello is a known terminating example. Other v1 images lack safepoints.
 if(hdr[0]==0x31415853u && (len!=160 || hdr[2]!=0x3177c71bu))return TAG(-1);
 __asm__ volatile("fence.i":::"memory");
 j->polls=j->yields=0;j->status=RUNNING;
 j->actor=fpr_g_spawn_call1(slot?(V)&second_entry:(V)&first_entry);
 latest=slot;
 return TAG(slot+1);
}
FPR_FN(fpr_g_spectreRun,app_run,1);
