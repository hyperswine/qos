/* Early QOS vector splash. No GL context, DRM master, daemon or image library.
 * --ppm FILE WIDTH HEIGHT renders the identical geometry for host validation.
 */
#include "boot_logo.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __linux__
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/kd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#endif

static int ppm(const char *path, int w, int h) {
  if (w < 64 || h < 64 || w > 8192 || h > 8192) return 1;
  FILE *f = fopen(path, "wb");
  if (!f) return 1;
  fprintf(f, "P6\n%d %d\n255\n", w, h);
  qos_logo_layout layout = qos_boot_logo_layout(w, h);
  for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
    uint32_t c = qos_boot_logo_rgb(layout, x, y);
    unsigned char rgb[] = {c >> 16, c >> 8, c};
    if (fwrite(rgb, 1, 3, f) != 3) { fclose(f); return 1; }
  }
  return fclose(f) != 0;
}

#ifdef __linux__
static uint32_t component(unsigned color, struct fb_bitfield field) {
  return ((color * ((1u << field.length) - 1u) + 127u) / 255u) << field.offset;
}

static int framebuffer(const char *path) {
  int fd = open(path, O_RDWR | O_CLOEXEC);
  if (fd < 0) return 1;
  struct fb_fix_screeninfo fix;
  struct fb_var_screeninfo var;
  if (ioctl(fd, FBIOGET_FSCREENINFO, &fix) || ioctl(fd, FBIOGET_VSCREENINFO, &var)) goto fail;
  unsigned bytes = var.bits_per_pixel / 8;
  if (fix.type != FB_TYPE_PACKED_PIXELS || fix.visual != FB_VISUAL_TRUECOLOR ||
      (bytes != 2 && bytes != 3 && bytes != 4) || var.bits_per_pixel != bytes * 8 ||
      !var.xres || !var.yres || var.xres > 8192 || var.yres > 8192 ||
      ((uint64_t)var.xoffset + var.xres) * bytes > fix.line_length ||
      ((uint64_t)var.yoffset + var.yres) * fix.line_length > fix.smem_len) goto fail;
  struct fb_bitfield fields[] = {var.red, var.green, var.blue, var.transp};
  for (unsigned i = 0; i < 4; i++)
    if (fields[i].length > 8 || fields[i].offset + fields[i].length > var.bits_per_pixel || fields[i].msb_right) goto fail;
  unsigned char *map = mmap(NULL, fix.smem_len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (map == MAP_FAILED) goto fail;
  int tty = open("/dev/tty1", O_RDWR | O_CLOEXEC);
  if (tty >= 0) {
    ioctl(tty, KDSETMODE, KD_GRAPHICS);
    close(tty); /* VT stays in graphics mode until QOS takes over. */
  }
  unsigned char *start = map + (size_t)var.yoffset * fix.line_length + var.xoffset * bytes;
  if (bytes == 4 && var.red.offset == 16 && var.green.offset == 8 && var.blue.offset == 0 &&
      var.red.length == 8 && var.green.length == 8 && var.blue.length == 8 && !var.transp.length) {
    qos_boot_logo_xrgb((uint32_t *)start, fix.line_length, (int)var.xres, (int)var.yres);
  } else {
    qos_logo_layout layout = qos_boot_logo_layout((int)var.xres, (int)var.yres);
    for (unsigned y = 0; y < var.yres; y++) for (unsigned x = 0; x < var.xres; x++) {
      uint32_t c = qos_boot_logo_rgb(layout, (int)x, (int)y);
      uint32_t out = component((c >> 16) & 255, var.red) |
                     component((c >> 8) & 255, var.green) |
                     component(c & 255, var.blue) | component(255, var.transp);
      memcpy(start + (size_t)y * fix.line_length + x * bytes, &out, bytes);
    }
  }
  munmap(map, fix.smem_len);
  close(fd);
  fprintf(stderr, "qosp-splash: displayed %ux%u %ubpp on %s\n",
          var.xres, var.yres, var.bits_per_pixel, path);
  return 0;
fail:
  close(fd);
  return 1;
}
#endif

int main(int argc, char **argv) {
  if (argc == 5 && !strcmp(argv[1], "--ppm")) return ppm(argv[2], atoi(argv[3]), atoi(argv[4]));
#ifdef __linux__
  if (argc == 1 || (argc == 3 && !strcmp(argv[1], "--fbdev"))) {
    const char *path = argc == 3 ? argv[2] : "/dev/fb0";
    if (!framebuffer(path)) return 0;
    fprintf(stderr, "qosp-splash: framebuffer unavailable or unsupported: %s\n", path);
    return 1;
  }
#endif
  fprintf(stderr, "usage: qosp-splash [--fbdev /dev/fb0] | --ppm FILE WIDTH HEIGHT\n");
  return 2;
}
