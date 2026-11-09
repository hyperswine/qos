#include <stdio.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <pthread.h>
#include <fcntl.h>
static uint64_t now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000000000ull+t.tv_nsec;}
#define N 2000000
static int p1[2],p2[2];
static void*echo(void*a){char c;for(int i=0;i<200000;i++){read(p1[0],&c,1);write(p2[1],&c,1);}return 0;}
int main(void){
  for(int r=0;r<3;r++){
  uint64_t t=now(); for(int i=0;i<N;i++) syscall(SYS_getppid); uint64_t d=now()-t;
  printf("getppid (raw syscall)   %.1f ns\n",(double)d/N);
  int fd=open("/dev/null",O_WRONLY); char b=0;
  t=now(); for(int i=0;i<N;i++) write(fd,&b,1); d=now()-t;
  printf("write 1B /dev/null      %.1f ns\n",(double)d/N);
  }
  pipe(p1);pipe(p2);pthread_t th;pthread_create(&th,0,echo,0);
  char c=1; uint64_t t=now(); for(int i=0;i<200000;i++){write(p1[1],&c,1);read(p2[0],&c,1);} uint64_t d=now()-t;
  printf("pipe ping-pong 2 threads %.1f ns per round trip\n",(double)d/200000);
  return 0;}
