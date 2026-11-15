// Single hart only. No scheduler calls inside an interrupt-masked RMW.
#if FPR_NHARTS != 1
#error requires one hart
#endif
static unsigned lock(void){unsigned s;__asm__ volatile("csrrci %0,mstatus,8; fence rw,rw":"=r"(s)::"memory");return s;}
static void unlock(unsigned s){__asm__ volatile("fence rw,rw":::"memory");if(s&8)__asm__ volatile("csrsi mstatus,8":::"memory");}
#define OP(n,v) unsigned n(volatile void *p,unsigned x,int order){(void)order;unsigned s=lock(),a=*(volatile unsigned*)p;*(volatile unsigned*)p=(v);unlock(s);return a;}
OP(__atomic_fetch_add_4,a+x)
OP(__atomic_fetch_sub_4,a-x)
OP(__atomic_fetch_or_4,a|x)
OP(__atomic_exchange_4,x)
_Bool __atomic_compare_exchange_4(volatile void*p,void*expected,unsigned x,_Bool weak,int success,int failure){(void)weak;(void)success;(void)failure;unsigned s=lock(),a=*(volatile unsigned*)p;_Bool ok=a==*(unsigned*)expected;if(ok)*(volatile unsigned*)p=x;else *(unsigned*)expected=a;unlock(s);return ok;}
