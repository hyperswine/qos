#include "fpr.h"
static fpr_plane_actors_t p;
static fpr_plane_memory_t mem;
static V parent;
// Single-hart Spectre: complete a level IRQ only after draining RXDATA.
#define MM(a) (*(volatile unsigned *)(a))
#define STATUS MM(0x10000004)
#define RX MM(0x10000008)
#define CTRL MM(0x1000000c)
#define ENABLE MM(0x0c002000)
#define CLAIM MM(0x0c200004)
static unsigned claims,acks;
static volatile unsigned external_wakes;
extern void __real_hal_wfi(void);
void __wrap_hal_wfi(void){
 unsigned pre,post;
 __asm__ volatile("csrr %0,mip":"=r"(pre)::"memory");
 __real_hal_wfi();
 __asm__ volatile("csrr %0,mip":"=r"(post)::"memory");
 if(!(pre&2048) && (post&2048))external_wakes++;
}
static void say(const char*s){while(*s)hal_putc(*s++);}
static void fail(void){say("FAIL uart\n");for(;;);}
void hal_irq_open(uw src){if(src!=10)fail();MM(0x0c000028)=1;MM(0x0c200000)=0;ENABLE=1u<<10;}
sw hal_irq_claim(void){unsigned s=CLAIM;if(s){if(s!=10)fail();ENABLE=0;claims++;}return s;}
void hal_irq_ack(uw src){if(src!=10)fail();CLAIM=10;ENABLE=1u<<10;acks++;}
extern V fpr_g_Sys_x2eirqInstall_call1(V),fpr_g_Sys_x2eirqTarget_call1(V),
 fpr_g_Sys_x2eirqOpen_call1(V),fpr_g_Sys_x2eirqAck_call1(V);
static V worker(V me){
 if(fpr_g_Sys_x2eirqInstall_call1(me)!=(V)&fpr_true)fail();
 fpr_g_Sys_x2eirqTarget_call1(TAG(1));
 fpr_g_Sys_x2eirqOpen_call1(TAG(10));CTRL=1;
 for(int i=0;i<2;i++){
 unsigned wakes=external_wakes;say(i?"READY B\n":"READY A\n");
 if(p.receive(me)!=TAG(10)||!(STATUS&2)||external_wakes==wakes)fail();
 unsigned byte=RX&255;fpr_g_Sys_x2eirqAck_call1(TAG(10));
 if(!fpr_sent(p.send_as((uw)me,parent,TAG(byte))))fail();
 }
 if(p.receive(me)!=TAG(99))fail();
 if(!fpr_sent(p.send_as((uw)me,parent,TAG(100))))fail();
 for(;;)p.receive(me);
}
FPR_FN(spectre_worker,worker,1);
V fpr_fn_main(void){
 fpr_plane_export(&p,&mem);parent=(V)fpr_hart()->current;
 V child=p.spawn((V)&spectre_worker);
 for(int i=0;i<2;i++){
 if(p.receive(parent)!=TAG(i?0x5a:0x41))fail();
 say(i?"received 5a\n":"received 41\n");
 }
 p.sleep_us(10000);
 if(!fpr_sent(p.send_as((uw)parent,child,TAG(99))) || p.receive(parent)!=TAG(100) || claims!=2 || acks!=2)fail();
 say("2 claims/acks; scheduler ping/pong OK\nDONE");for(;;);
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
