#include "fpr.h"
static fpr_plane_actors_t p;
static fpr_plane_memory_t mem;
static V parent;
#include "sd.h"
#define LBA 131072u
static unsigned char block[512];
static void say(const char*s){while(*s)hal_putc(*s++);}
static unsigned get(void){volatile unsigned*u=(void*)0x10000000;while(!(u[1]&2))p.fuel();return u[2]&255;}
static void hex(unsigned x){const char*h="0123456789abcdef";hal_putc(h[x>>4]);hal_putc(h[x&15]);}
static unsigned nib(void){unsigned x=get();if(x>='0'&&x<='9')return x-'0';if(x>='a'&&x<='f')return x-'a'+10;return 16;}
static void fail(void){say("FAIL\n");for(;;);}
static V store(V me){
 (void)me;sd_card_t card;sd_use_dma(0);
 int r=sd_init(&card,15);if(r){say("init error ");hex(-r&255);fail();}
 if(card.blocks<=LBA)fail();
 say("CID ");for(int i=0;i<16;i++)hex(card.cid[i]);say("\n");
 for(;;){say("READY\n");unsigned op=get();
 if(op=='R'){if(sd_read(&card,LBA,block))fail();say("DATA ");for(int i=0;i<512;i++)hex(block[i]);say("\n");}
 else if(op=='W'){for(int i=0;i<512;i++){unsigned a=nib(),b=nib();if(a>15||b>15)fail();block[i]=16*a+b;}if(sd_write(&card,LBA,block))fail();say("WROTE\n");}
 else fail();}
}
FPR_FN(storage_actor,store,1);
V fpr_fn_main(void){fpr_plane_export(&p,&mem);p.spawn((V)&storage_actor);return p.receive((V)fpr_hart()->current);}
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
