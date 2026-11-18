#include "fpr.h"
static fpr_plane_actors_t p;
static fpr_plane_memory_t mem;
static V parent;
static volatile unsigned parked, wakes;
static void say(const char*s){while(*s)hal_putc(*s++);}
static void fail(void){say("FAIL idle probe\n");for(;;);}
extern void __real_hal_wfi(void);
void __wrap_hal_wfi(void){
 unsigned mie,pre,post;
 __asm__ volatile("csrr %0,mie":"=r"(mie));
 uint64_t t=hal_mtime();
 __asm__ volatile("csrr %0,mip":"=r"(pre)::"memory");
 __real_hal_wfi();
 __asm__ volatile("csrr %0,mip":"=r"(post)::"memory");
 if(parked==3 && !(pre&mie) && (post&mie)==128 && hal_mtime()-t>=10000) wakes++;
}
static void nap(unsigned bit,unsigned us){
 uint64_t t=hal_mtime();parked|=bit;p.sleep_us(us);parked&=~bit;
 if(hal_mtime()-t<(uint64_t)us*10)fail();
}
static V worker(V me){
 for(int i=1;i<=3;i++){
 if(p.receive(me)!=TAG(i))fail();
 nap(2,18000);
 if(p.receive(me)!=TAG(100+i))fail();
 if(!fpr_sent(p.send_as((uw)me,parent,TAG(200+i))))fail();
 }
 return TAG(0);
}
FPR_FN(spectre_worker,worker,1);
V fpr_fn_main(void){
 fpr_plane_export(&p,&mem);parent=(V)fpr_hart()->current;
 V child=p.spawn((V)&spectre_worker);
 for(int i=1;i<=3;i++){
 unsigned before=wakes;
 if(!fpr_sent(p.send_as((uw)parent,child,TAG(i))))fail();
 nap(1,10000);
 if(wakes==before)fail();
 if(!fpr_sent(p.send_as((uw)parent,child,TAG(100+i))))fail();
 if(p.receive(parent)!=TAG(200+i))fail();
 say("both parked; WFI -> MTIP; ping/pong OK\n");
 }
 say("spectre idle OK\nDONE");for(;;);
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
#elif !defined(CORE_MHZ) /* the board build passes -DCORE_MHZ */
#define CORE_MHZ 54
#endif
uint64_t hal_mtime(void){uint64_t n=spectre_raw_ticks();return n/CORE_MHZ*10+(n%CORE_MHZ)*10/CORE_MHZ;}
void hal_timer_arm(uw hart,uint64_t delta){spectre_raw_arm(hart,delta/10*CORE_MHZ+((delta%10)*CORE_MHZ+9)/10);}
