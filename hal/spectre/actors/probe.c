#include "fpr.h"
static fpr_plane_actors_t p;
static fpr_plane_memory_t mem;
static V parent;
static volatile unsigned turns,waiting;
static void say(const char*s){while(*s)hal_putc(*s++);}
static void fail(void){say("FAIL\n");for(;;);}
static V worker(V me){
 for(int i=1;i<=3;i++){
 V msg=p.receive(me);if(msg!=TAG(i))fail();
 if(!fpr_sent(p.send_as((uw)fpr_hart()->current,parent,TAG(10+i))))fail();
 while(waiting==(unsigned)i){turns++;p.fuel();}
 }
 return TAG(0);
}
FPR_FN(spectre_worker,worker,1);
V fpr_fn_main(void){
 fpr_plane_export(&p,&mem);
 parent=(V)fpr_hart()->current;
 V child=p.spawn((V)&spectre_worker);
 for(int i=1;i<=3;i++){
 waiting=i;
 if(!fpr_sent(p.send_as((uw)fpr_hart()->current,child,TAG(i))))fail();
 if(p.receive(parent)!=TAG(10+i))fail();
 unsigned before=turns;uint64_t t=hal_mtime();
 p.sleep_us(10000);
 if(hal_mtime()-t<100000 || turns==before)fail();
 waiting=0;say("ping/pong; elapsed deadline; peer advanced\n");p.fuel();
 }
 say("spectre actors OK\nDONE");for(;;);
}
void fpr_builtin_main(void){say("spectre boot\n");fpr_rt_init();fpr_hart_main(0);}
void hal_putc(char c){
#ifdef TEST_QEMU
volatile unsigned char *q=(void*)0x10000000;while(!(q[5]&32));q[0]=c;return;
#endif
volatile unsigned*u=(void*)0x10000000;while(!(u[1]&1));*u=c;}
void hal_poweroff(int code){(void)code;fail();}

// The scheduler uses a 10 MHz timebase; the board CLINT counts CPU clocks.
extern uint64_t spectre_raw_ticks(void);
extern void spectre_raw_arm(uw,uint64_t);
#ifdef TEST_QEMU
#define CORE_MHZ 10
#else
#define CORE_MHZ 54
#endif
uint64_t hal_mtime(void){uint64_t n=spectre_raw_ticks();return n/CORE_MHZ*10+(n%CORE_MHZ)*10/CORE_MHZ;}
void hal_timer_arm(uw hart,uint64_t delta){spectre_raw_arm(hart,delta/10*CORE_MHZ+((delta%10)*CORE_MHZ+9)/10);}
