/* KMS CPU presentation: RGB order, vertical orientation, pitch and scaling. */
#include "drm_scanout.h"
#include <assert.h>
int main(void) {
  unsigned char pixels[] = {255,0,0,255, 0,255,0,255,
                           0,0,255,255, 255,255,255,255};
  uint32_t map[8 * 4];
  drm_out_t o = {.on=1, .gw=2, .gh=2, .mw=6, .mh=4, .pitch=8*4,
                 .rd=pixels, .map=map};
  for (int mode=0; mode<=2; mode++) {
    for (int i=0;i<32;i++) map[i]=0xabcdef;
    o.scale=mode; drm_scanout_present(&o);
    for (int y=0;y<4;y++) assert(map[y*8+6]==0xabcdef && map[y*8+7]==0xabcdef);
    if (mode==0) {
      assert(map[8+2]==0x0000ff && map[8+3]==0xffffff);
      assert(map[16+2]==0xff0000 && map[16+3]==0x00ff00);
      assert(map[0]==0xabcdef && map[31]==0xabcdef);
    } else if (mode==1) {
      assert(map[1]==0x0000ff && map[4]==0xffffff);
      assert(map[25]==0xff0000 && map[28]==0x00ff00);
      for(int y=0;y<4;y++) assert(map[y*8]==0xabcdef && map[y*8+5]==0xabcdef);
    } else {
      assert(map[0]==0x0000ff && map[2]==0x0000ff && map[3]==0xffffff && map[5]==0xffffff);
      assert(map[24]==0xff0000 && map[29]==0x00ff00);
    }
  }
  puts("DRM_SCANOUT_PASS RGB orientation pitch native fit fill");
  return 0;
}
