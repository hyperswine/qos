/* QOS boot wordmark: SVG strokes rasterized at the display's resolution.
 * Shared by the early fbdev splash and KMS's initial framebuffer so the
 * logo survives the display handoff until the application draws a frame.
 */
#ifndef QOS_BOOT_LOGO_H
#define QOS_BOOT_LOGO_H
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include "boot_logo_data.h"

#define QOS_BOOT_BACKGROUND 0x070b12u
typedef struct { float scale, left, top; } qos_logo_layout;

static inline qos_logo_layout qos_boot_logo_layout(int w, int h) {
  float scale = fminf(fminf(w * 0.35f / 256.0f, h * 0.35f / 96.0f), 1.75f);
  return (qos_logo_layout){scale, (w - 256 * scale) * 0.5f, (h - 96 * scale) * 0.5f};
}

static inline float qos_logo_segment(float x, float y, qos_logo_point a, qos_logo_point b) {
  float dx = b.x - a.x, dy = b.y - a.y, den = dx * dx + dy * dy;
  float t = den ? fminf(1, fmaxf(0, ((x - a.x) * dx + (y - a.y) * dy) / den)) : 0;
  dx = x - a.x - t * dx; dy = y - a.y - t * dy;
  return sqrtf(dx * dx + dy * dy);
}

static inline uint32_t qos_boot_logo_rgb(qos_logo_layout layout, int px, int py) {
  float x = (px + 0.5f - layout.left) / layout.scale;
  float y = (py + 0.5f - layout.top) / layout.scale;
  uint32_t rgb = QOS_BOOT_BACKGROUND;
  if (x < 0 || x > 256 || y < 0 || y > 96) return rgb;
  for (unsigned i = 0; i < sizeof qos_logo_strokes / sizeof qos_logo_strokes[0]; i++) {
    const qos_logo_stroke *s = &qos_logo_strokes[i];
    float distance = 1.0e6f;
    if (s->count == 1) {
      float dx = x - s->points[0].x, dy = y - s->points[0].y;
      distance = fabsf(sqrtf(dx * dx + dy * dy) - s->points[0].radius);
    } else {
      for (int j = 1; j < s->count; j++)
        distance = fminf(distance, qos_logo_segment(x, y, s->points[j - 1], s->points[j]));
    }
    float alpha = fminf(1, fmaxf(0, 0.5f - (distance - s->width * 0.5f) * layout.scale));
    uint32_t result = 0;
    for (int shift = 0; shift <= 16; shift += 8) {
      float from = (float)((rgb >> shift) & 255), to = (float)((s->color >> shift) & 255);
      result |= (uint32_t)(from + alpha * (to - from) + 0.5f) << shift;
    }
    rgb = result;
  }
  return rgb;
}

static inline void qos_boot_logo_xrgb(uint32_t *pixels, unsigned pitch, int w, int h) {
  qos_logo_layout layout = qos_boot_logo_layout(w, h);
  for (int y = 0; y < h; y++) {
    uint32_t *row = pixels + (size_t)y * (pitch / 4);
    for (int x = 0; x < w; x++) row[x] = QOS_BOOT_BACKGROUND;
  }
  int x0 = (int)layout.left, y0 = (int)layout.top;
  int x1 = (int)(layout.left + 256 * layout.scale + 1);
  int y1 = (int)(layout.top + 96 * layout.scale + 1);
  for (int y = y0; y < y1 && y < h; y++)
    for (int x = x0; x < x1 && x < w; x++)
      pixels[(size_t)y * (pitch / 4) + x] = qos_boot_logo_rgb(layout, x, y);
}
#endif
