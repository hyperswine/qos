#include "boot_logo.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
  const int sizes[][2] = {{64,64}, {240,320}, {641,480}, {1024,768}, {1921,1081}};
  for (unsigned n = 0; n < sizeof sizes / sizeof sizes[0]; n++) {
    int w = sizes[n][0], h = sizes[n][1], stride = w + 7;
    size_t count = (size_t)stride * h + 2;
    uint32_t *map = malloc(count * sizeof *map);
    assert(map);
    for (size_t i = 0; i < count; i++) map[i] = 0xdeadbeef;
    qos_boot_logo_xrgb(map + 1, (unsigned)stride * 4, w, h);
    assert(map[0] == 0xdeadbeef && map[count - 1] == 0xdeadbeef);
    int white = 0, cyan = 0;
    for (int y = 0; y < h; y++) {
      for (int x = w; x < stride; x++) assert(map[1 + (size_t)y * stride + x] == 0xdeadbeef);
      for (int x = 0; x < w; x++) {
        uint32_t rgb = map[1 + (size_t)y * stride + x];
        assert((rgb & 0xff000000) == 0);
        if (rgb == 0xf3f6fc) white++;
        if (rgb == 0x4cc9f0) cyan++;
        if (x < w / 4 || x >= w * 3 / 4 || y < h / 4 || y >= h * 3 / 4)
          assert(rgb == QOS_BOOT_BACKGROUND);
      }
    }
    if (w > 64) assert(white > 100 && cyan > 10);
    free(map);
  }
  puts("BOOT_LOGO_PASS centering colors bounds padded stride portrait-safe sizing");
  return 0;
}
