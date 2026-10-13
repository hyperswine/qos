/* drm_scanout.h -- the monitor link: a KMS dumb-buffer present for the
 * gfx tier, raw DRM uapi ioctls only (kernel headers, no libdrm).
 *
 * The gfx tier renders into an offscreen FBO (surfaceless EGL); this
 * header adds the last hop the fpr-linux-shell's C shim proved out:
 * pick the first /dev/dri/card* with a connected connector, take its
 * preferred mode, create one dumb XRGB framebuffer, SetCrtc once, and
 * per frame glReadPixels the FBO and blit it centered (vertically
 * flipped -- GL rows run bottom-up) into the mapping. gfx.c can instead
 * import its exported dma-buf and perform that transfer on the GPU.
 *
 * Wholly optional and self-disabling: no /dev/dri, no connected
 * display, no DRM master (a compositor holds it), or FPR_DRM=0 all
 * mean "render offscreen exactly as before", one stderr line says
 * which.  A dumb buffer + SetCrtc is deliberately the simplest
 * possible scanout: no GBM, no EGL surfaces, no page flipping --
 * tearing is possible and stated.  vc4 on a Pi 4 exposes the KMS
 * node as card0 or card1 depending on boot config; the v3d render
 * node has no connectors and is skipped by the probe. */
#ifndef DRM_SCANOUT_H
#define DRM_SCANOUT_H

#include <drm/drm.h>
#include "hostlog.h"
#include <drm/drm_mode.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <linux/kd.h>
#include "boot_logo.h"

typedef struct {
  int fd;
  uint32_t *map;      /* the dumb buffer, XRGB8888, pitch/4 px per row */
  uint32_t pitch;     /* bytes per row */
  uint32_t mw, mh;    /* mode size */
  unsigned char *rd;  /* RGBA readback scratch, gw*gh*4 */
  int gw, gh;         /* the GL FBO size */
  uint32_t fb_id;     /* the framebuffer, for DIRTYFB */
  uint32_t gem_handle; /* exportable backing storage for optional GPU blits */
  int dirty;          /* this driver wants to be told what changed */
  int on;
  int scale; /* 0 native pixels, 1 aspect fit, 2 fill the monitor */
} drm_out_t;

/* A fbcon VT left in KD_TEXT can restore its own CRTC on keyboard activity.
 * Hold this appliance's VT in graphics mode while KMS owns the picture. */
static int drm_console_fd = -1, drm_console_mode;
static void drm_console_restore(void) {
  if (drm_console_fd >= 0) {
    ioctl(drm_console_fd, KDSETMODE, drm_console_mode);
    close(drm_console_fd);
    drm_console_fd = -1;
  }
}
static void drm_console_acquire(void) {
  const char *tty = getenv("FPR_DRM_TTY");
  if (!tty || !*tty) tty = "/dev/tty1";
  int fd = open(tty, O_RDWR | O_CLOEXEC);
  int mode;
  if (fd < 0 || ioctl(fd, KDGETMODE, &mode) < 0 ||
      ioctl(fd, KDSETMODE, KD_GRAPHICS) < 0) {
    qos_hostlog("[gfx] %s: graphics console mode unavailable (%s)", tty, strerror(errno));
    if (fd >= 0) close(fd);
    return;
  }
  drm_console_fd = fd; drm_console_mode = mode;
  atexit(drm_console_restore);
  qos_hostlog("[gfx] %s: graphics console mode", tty);
}

static int drm_try_card(drm_out_t *o, const char *path, int gw, int gh) {
  int fd = open(path, O_RDWR | O_CLOEXEC);
  if (fd < 0) return 0;

  struct drm_mode_card_res res;
  memset(&res, 0, sizeof res);
  if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res) < 0 || !res.count_connectors) {
    close(fd);
    return 0; /* a render node (v3d) or no KMS */
  }
  uint32_t conns[32], crtcs[32];
  if (res.count_connectors > 32) res.count_connectors = 32;
  if (res.count_crtcs > 32) res.count_crtcs = 32;
  res.connector_id_ptr = (uintptr_t)conns;
  res.crtc_id_ptr = (uintptr_t)crtcs;
  res.count_fbs = res.count_encoders = 0;
  res.fb_id_ptr = res.encoder_id_ptr = 0;
  if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res) < 0) {
    close(fd);
    return 0;
  }

  /* Only the DRM MASTER may modeset.  A process is master automatically
   * only when it is the first to open the primary node, which we are not:
   * on a console image the kernel's fbdev emulation has already opened it
   * (that is what puts a text console on the screen).  Without this the
   * probe gets all the way to SetCrtc and fails there with EACCES, which
   * reads as a permissions problem and is not one.
   *
   * It legitimately fails when something else IS master -- a compositor,
   * or another qosp -- and then this card is simply not ours: say so and
   * let the caller try the next one, or render offscreen. */
  if (ioctl(fd, DRM_IOCTL_SET_MASTER, 0) < 0) {
    qos_hostlog("[gfx] %s: not DRM master (%s) -- another process holds the "
                "display", path, strerror(errno));
    close(fd);
    return 0;
  }

  /* first CONNECTED connector, preferred (first) mode */
  struct drm_mode_modeinfo modes[64];
  struct drm_mode_get_connector c;
  uint32_t conn_id = 0;
  struct drm_mode_modeinfo mode;
  uint32_t enc_id = 0;
  for (uint32_t i = 0; i < res.count_connectors; i++) {
    memset(&c, 0, sizeof c);
    c.connector_id = conns[i];
    if (ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &c) < 0) continue;
    if (c.connection != 1 /* connected */ || !c.count_modes) continue;
    if (c.count_modes > 64) c.count_modes = 64;
    memset(&c, 0, sizeof c);
    c.connector_id = conns[i];
    c.count_modes = 64;
    c.modes_ptr = (uintptr_t)modes;
    if (ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &c) < 0) continue;
    if (c.connection != 1 || !c.count_modes) continue;
    conn_id = conns[i];
    mode = modes[0];
    enc_id = c.encoder_id;
    break;
  }
  if (!conn_id) {
    close(fd);
    return 0;
  }

  /* the CRTC: the connector's live encoder's crtc, else the first */
  uint32_t crtc_id = 0;
  if (enc_id) {
    struct drm_mode_get_encoder e;
    memset(&e, 0, sizeof e);
    e.encoder_id = enc_id;
    if (ioctl(fd, DRM_IOCTL_MODE_GETENCODER, &e) == 0 && e.crtc_id)
      crtc_id = e.crtc_id;
  }
  if (!crtc_id && res.count_crtcs) crtc_id = crtcs[0];
  if (!crtc_id) {
    close(fd);
    return 0;
  }

  struct drm_mode_create_dumb cd;
  memset(&cd, 0, sizeof cd);
  cd.width = mode.hdisplay;
  cd.height = mode.vdisplay;
  cd.bpp = 32;
  if (ioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &cd) < 0) {
    close(fd);
    return 0;
  }
  struct drm_mode_fb_cmd fb;
  memset(&fb, 0, sizeof fb);
  fb.width = cd.width;
  fb.height = cd.height;
  fb.pitch = cd.pitch;
  fb.bpp = 32;
  fb.depth = 24;
  fb.handle = cd.handle;
  if (ioctl(fd, DRM_IOCTL_MODE_ADDFB, &fb) < 0) {
    close(fd);
    return 0;
  }
  struct drm_mode_map_dumb md;
  memset(&md, 0, sizeof md);
  md.handle = cd.handle;
  if (ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &md) < 0) {
    close(fd);
    return 0;
  }
  void *map = mmap(0, cd.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd,
                   (off_t)md.offset);
  if (map == MAP_FAILED) {
    close(fd);
    return 0;
  }
  memset(map, 0, cd.size);
  const char *splash = getenv("FPR_BOOT_SPLASH");
  if (splash && !strcmp(splash, "1"))
    qos_boot_logo_xrgb((uint32_t *)map, cd.pitch, (int)cd.width, (int)cd.height);

  struct drm_mode_crtc crtc;
  memset(&crtc, 0, sizeof crtc);
  crtc.crtc_id = crtc_id;
  crtc.fb_id = fb.fb_id;
  crtc.set_connectors_ptr = (uintptr_t)&conn_id;
  crtc.count_connectors = 1;
  crtc.mode = mode;
  crtc.mode_valid = 1;
  if (ioctl(fd, DRM_IOCTL_MODE_SETCRTC, &crtc) < 0) {
    /* we are master by here, so this is the mode or the CRTC, not access */
    qos_hostlog("[gfx] %s: SetCrtc failed (%s) -- rendering offscreen",
                path, strerror(errno));
    munmap(map, cd.size);
    close(fd);
    return 0;
  }

  o->fd = fd;
  o->map = (uint32_t *)map;
  o->fb_id = fb.fb_id;
  o->gem_handle = cd.handle;
  o->dirty = 1; /* until a driver says it does not want to be told */
  o->pitch = cd.pitch;
  o->mw = mode.hdisplay;
  o->mh = mode.vdisplay;
  o->gw = gw;
  o->gh = gh;
  /* gw==0: the AUTO path -- caller sizes the frame to the mode and
   * allocates rd itself once it knows */
  o->rd = gw ? (unsigned char *)malloc((size_t)gw * gh * 4) : 0;
  o->on = gw ? (o->rd != 0) : 1;
  const char *scale = getenv("FPR_DRM_SCALE");
  o->scale = scale && !strcmp(scale, "fill") ? 2 : scale && !strcmp(scale, "fit") ? 1 : 0;
  qos_hostlog("[gfx] scanout: %s %ux%u (frame %s)", path, o->mw, o->mh,
              o->scale == 2 ? "fill" : o->scale == 1 ? "fit" : gw ? "centered" : "fullscreen");
  return o->on;
}

static void drm_scanout_init(drm_out_t *o, int gw, int gh) {
  memset(o, 0, sizeof *o);
  const char *e = getenv("FPR_DRM");
  if (e && e[0] == '0') return; /* explicitly off */
  const char *cards[] = {"/dev/dri/card0", "/dev/dri/card1", "/dev/dri/card2"};
  for (int i = 0; i < 3; i++)
    if (drm_try_card(o, cards[i], gw, gh)) { drm_console_acquire(); return; }
}

static int drm_scanout_export_fd(const drm_out_t *o) {
  struct drm_prime_handle prime;
  memset(&prime, 0, sizeof prime);
  prime.handle = o->gem_handle;
  prime.flags = DRM_CLOEXEC | DRM_RDWR;
  if (ioctl(o->fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) < 0) return -1;
  return prime.fd;
}

/* Shared placement policy for CPU copies and GPU framebuffer blits. */
static void drm_scanout_rect(const drm_out_t *o, int *x, int *y, int *outw, int *outh) {
  int w = ((uint32_t)o->gw < o->mw) ? o->gw : (int)o->mw;
  int h = ((uint32_t)o->gh < o->mh) ? o->gh : (int)o->mh;
  if (o->scale) {
    w = (int)o->mw; h = (int)o->mh;
    if (o->scale == 1) {
      if ((uint64_t)w * o->gh > (uint64_t)h * o->gw) w = (int)((uint64_t)h * o->gw / o->gh);
      else h = (int)((uint64_t)w * o->gh / o->gw);
    }
  }
  uint32_t x0 = (o->mw - (uint32_t)w) / 2;
  uint32_t y0 = (o->mh - (uint32_t)h) / 2;
  *x = (int)x0; *y = (int)y0; *outw = w; *outh = h;
}

static void drm_scanout_damage(drm_out_t *o, int x0, int y0, int w, int h) {
  /* Paravirtual displays copy only the region they are told changed.
   * Physical scanout hardware usually does not implement this ioctl. */
  if (o->dirty) {
    struct drm_clip_rect clip;
    clip.x1 = (unsigned short)x0;
    clip.y1 = (unsigned short)y0;
    clip.x2 = (unsigned short)(x0 + w);
    clip.y2 = (unsigned short)(y0 + h);
    struct drm_mode_fb_dirty_cmd d;
    memset(&d, 0, sizeof d);
    d.fb_id = o->fb_id;
    d.num_clips = 1;
    d.clips_ptr = (uintptr_t)&clip;
    if (ioctl(o->fd, DRM_IOCTL_MODE_DIRTYFB, &d) < 0) o->dirty = 0;
  }
}

/* readback + centered, v-flipped RGBA -> XRGB blit.  rd was filled by
 * glReadPixels(0,0,gw,gh) -- row 0 is the BOTTOM of the image. */
static void drm_scanout_present(drm_out_t *o) {
  if (!o->on) return;
  int x0, y0, w, h;
  drm_scanout_rect(o, &x0, &y0, &w, &h);
  for (int y = 0; y < h; y++) {
    int sy = o->scale ? (int)((uint64_t)y * o->gh / h) : y;
    const unsigned char *src = o->rd + (size_t)(o->gh - 1 - sy) * o->gw * 4;
    uint32_t *dst = o->map + (size_t)(y0 + y) * (o->pitch / 4) + x0;
    for (int x = 0; x < w; x++) {
      int sx = o->scale ? (int)((uint64_t)x * o->gw / w) : x;
      dst[x] = ((uint32_t)src[sx * 4 + 0] << 16) |
               ((uint32_t)src[sx * 4 + 1] << 8) | src[sx * 4 + 2];
    }
  }

  drm_scanout_damage(o, x0, y0, w, h);
}

#endif /* DRM_SCANOUT_H */
