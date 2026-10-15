/* Read-only capture of the framebuffer selected by an active KMS CRTC.
 * No master acquisition, modeset, framebuffer allocation or pixel writes. */
#define _GNU_SOURCE
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define REQUIRE(x) do { if (!(x)) { perror(#x); return 1; } } while (0)
int main(int argc,char **argv) {
 if(argc!=3) return 2;
 int fd=open(argv[1],O_RDWR|O_CLOEXEC); REQUIRE(fd>=0);
 struct drm_mode_card_res res={0}; REQUIRE(ioctl(fd,DRM_IOCTL_MODE_GETRESOURCES,&res)==0);
 uint32_t ids[32]; REQUIRE(res.count_crtcs>0 && res.count_crtcs<=32);
 res.crtc_id_ptr=(uintptr_t)ids; res.count_connectors=res.count_encoders=res.count_fbs=0;
 REQUIRE(ioctl(fd,DRM_IOCTL_MODE_GETRESOURCES,&res)==0);
 struct drm_mode_crtc crtc={0};
 for(uint32_t i=0;i<res.count_crtcs;i++) {
  memset(&crtc,0,sizeof crtc); crtc.crtc_id=ids[i];
  REQUIRE(ioctl(fd,DRM_IOCTL_MODE_GETCRTC,&crtc)==0);
  if(crtc.mode_valid && crtc.fb_id) break;
 }
 REQUIRE(crtc.mode_valid && crtc.fb_id);
 struct drm_mode_fb_cmd fb={.fb_id=crtc.fb_id}; REQUIRE(ioctl(fd,DRM_IOCTL_MODE_GETFB,&fb)==0);
 REQUIRE(fb.handle && fb.bpp==32 && fb.depth==24 && fb.width>0 && fb.width<=8192 && fb.height>0 && fb.height<=8192 && fb.pitch>=fb.width*4);
 struct drm_mode_map_dumb map={.handle=fb.handle}; REQUIRE(ioctl(fd,DRM_IOCTL_MODE_MAP_DUMB,&map)==0);
 size_t size=(size_t)fb.pitch*fb.height;
 const unsigned char *pixels=mmap(0,size,PROT_READ,MAP_SHARED,fd,map.offset); REQUIRE(pixels!=MAP_FAILED);
 FILE *out=fopen(argv[2],"wb"); REQUIRE(out);
 fprintf(out,"P6\n%u %u\n255\n",fb.width,fb.height);
 unsigned char *row=malloc((size_t)fb.width*3); REQUIRE(row);
 for(uint32_t y=0;y<fb.height;y++) {
  for(uint32_t x=0;x<fb.width;x++) {
   const unsigned char *p=pixels+(size_t)y*fb.pitch+x*4;
   row[x*3]=p[2]; row[x*3+1]=p[1]; row[x*3+2]=p[0];
  }
  REQUIRE(fwrite(row,3,fb.width,out)==fb.width);
 }
 REQUIRE(fclose(out)==0); free(row); munmap((void*)pixels,size);
 struct drm_gem_close close_handle={.handle=fb.handle}; REQUIRE(ioctl(fd,DRM_IOCTL_GEM_CLOSE,&close_handle)==0);
 close(fd);
 fprintf(stderr,"KMS readback crtc=%u fb=%u %ux%u pitch=%u\n",crtc.crtc_id,crtc.fb_id,fb.width,fb.height,fb.pitch);
 return 0;
}
