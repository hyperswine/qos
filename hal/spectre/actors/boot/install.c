#include "sd.h"
extern const unsigned char media[],media_end[];
static uint8_t buf[512];
static void say(const char*s){volatile unsigned *u=(void*)0x10000000;while(*s){while(!(u[1]&1));*u=*s++;}}
void fpr_builtin_main(void){sd_card_t c;unsigned n=(media_end-media)/512;sd_use_dma(0);
if(sd_init(&c,15)||!n||n>4097||c.blocks<135168+n)goto fail;
if(sd_write(&c,135168,buf))goto fail;
for(unsigned i=1;i<=n;i++){unsigned j=i%n;const uint8_t *p=media+512*j;
if(sd_write(&c,135168+j,p)||sd_read(&c,135168+j,buf))goto fail;
for(unsigned k=0;k<512;k++)if(buf[k]!=p[k])goto fail;}
say("SD boot slot installed and compared\nDONE");for(;;);
fail:say("INSTALL FAILED\nDONE");for(;;);}
