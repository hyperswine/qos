// SDHC/SDXC SPI boot for Spectre (54 or 84 MHz: the SPI divisors keep card
// init under 400 kHz at both). Header: little-endian magic, bytes, CRC32.
// SLOT_LBA picks the boot slot: 135168 for Spectre-54, 139264 for Spectre-84.
typedef unsigned U;
#define SPI ((volatile U*)0x10001000)
#define UART ((volatile U*)0x10000000)
#ifndef SLOT_LBA
#define SLOT_LBA 135168u
#endif
#define BASE SLOT_LBA
static unsigned char x(U b){SPI[0]=b;while(SPI[1]&1);return SPI[0];}
static void cs(U on){SPI[2]=(15<<8)|on;}
static U cmd(U n,U arg,U crc){x(255);x(64+n);for(int i=24;i>=0;i-=8)x(arg>>i);x(crc);for(int i=0;i<16;i++){U r=x(255);if(r<128)return r;}return 255;}
static int readblk(U l, unsigned char *dst){cs(1);if(cmd(17,l,1))return 0;U r=255;for(U i=0;i<200000 && r==255;i++)r=x(255);if(r!=254)return 0;for(U i=0;i<512;i++)dst[i]=x(255);x(255);x(255);cs(0);x(255);return 1;}
static void say(const char*s){while(*s){while(!(UART[1]&1));UART[0]=*s++;}}
static U boot(void){
 SPI[2]=255<<8;for(int i=0;i<20;i++)x(255);SPI[2]|=1;
 U r=255;for(int i=0;i<50 && r!=1;i++)r=cmd(0,0,149);if(r!=1)return 1;
 if(cmd(8,426,135)!=1)return 2;
 U echo=0;for(int i=0;i<4;i++)echo=echo*256+x(255);if(echo!=426)return 3;
 for(U i=0;i<30000;i++){if(cmd(55,0,1)>1)return 4;r=cmd(41,1u<<30,1);if(!r)break;if(r!=1)return 5;}
 if(r||cmd(58,0,1))return 6;
 U o=x(255);x(255);x(255);x(255);if(!(o&64))return 7;
 cs(0);x(255);
 U h[128];if(!readblk(BASE,(void*)h)||h[0]!=0x31544253||!h[1]||h[1]>2*1024*1024)return 8;
 unsigned char *dst=(void*)0x80000000;U crc=~0u;
 for(U off=0;off<h[1];off+=512){if(!readblk(BASE+1+off/512,dst+off))return 9;
 for(U i=0;i<512 && off+i<h[1];i++){crc^=dst[off+i];for(U j=0;j<8;j++)crc=(crc>>1)^((0-(crc&1))&0xedb88320u);}}
 if(~crc!=h[2])return 10;
 say("Spectre SD boot OK\n");__asm__ volatile("fence.i; li t0,0x80000000; jr t0":::"t0","memory");return 11;
}
void rom_main(void){U e=boot();say("SD boot error ");while(!(UART[1]&1));UART[0]='A'+e;for(;;);}
