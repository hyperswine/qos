/* 2026-11-09: FP-RISC F32.sin/F32.cos (runtime.c fsin_/fcos_, copied verbatim from
 * fprisc e138e65 runtime/runtime.c lines 4505, 4523, 4566-4613) against libm
 * sinf/cosf over the yaw inputs gfx.c walk_entity produces. Build: cc -O2 trig-diff.c */
#include <stdint.h>
#include <stdio.h>
#include <math.h>
static uint64_t draw_(double d) { union { double d; uint64_t u; } c; c.d = d; return c.u; }
static int fspec_(double x) { return ((draw_(x) >> 52) & 0x7ff) == 0x7ff; } /* inf|nan */
static int rempio2_(double x, double *rp, int *okp) {
  const double P1 = 1.57079632673412561417e+00, P1T = 6.07710050650619224932e-11;
  *okp = 1;
  if (x > 1.0e15 || x < -1.0e15) { *okp = 0; return 0; } /* v1 range end */
  if (x > 1.073741824e9 || x < -1.073741824e9) {
    /* coarse 2pi spin-down first so the quadrant cast stays in range
     * (accuracy here is already ~ulp(x)-limited; documented v1) */
    x -= (double)(long long)(x * 1.59154943091895345608e-01) * 6.28318530717958647693e+00;
  }
  double nd = x * 6.36619772367581382433e-01; /* 2/pi */
  double n = (double)(long long)(nd + (nd >= 0.0 ? 0.5 : -0.5));
  *rp = (x - n * P1) - n * P1T;
  return ((long long)n) & 3;
}
static double ksin_(double r) {
  double r2 = r * r;
  return r * (1.0 + r2 * (-1.0 / 6 + r2 * (1.0 / 120 + r2 * (-1.0 / 5040
       + r2 * (1.0 / 362880 + r2 * (-1.0 / 39916800 + r2 * (1.0 / 6227020800.0
       + r2 * (-1.0 / 1307674368000.0 + r2 * (1.0 / 355687428096000.0)))))))));
}
static double kcos_(double r) {
  double r2 = r * r;
  return 1.0 + r2 * (-1.0 / 2 + r2 * (1.0 / 24 + r2 * (-1.0 / 720
       + r2 * (1.0 / 40320 + r2 * (-1.0 / 3628800 + r2 * (1.0 / 479001600.0
       + r2 * (-1.0 / 87178291200.0 + r2 * (1.0 / 20922789888000.0))))))));
}
static double fsin_(double x) {
  if (x != x || fspec_(x)) return 0.0 / 0.0;
  double r; int ok; int q = rempio2_(x, &r, &ok);
  if (!ok) return 0.0 / 0.0;
  switch (q) {
    case 0: return ksin_(r);
    case 1: return kcos_(r);
    case 2: return -ksin_(r);
    default: return -kcos_(r);
  }
}
static double fcos_(double x) {
  if (x != x || fspec_(x)) return 0.0 / 0.0;
  double r; int ok; int q = rempio2_(x, &r, &ok);
  if (!ok) return 0.0 / 0.0;
  switch (q) {
    case 0: return kcos_(r);
    case 1: return -ksin_(r);
    case 2: return -kcos_(r);
    default: return ksin_(r);
  }
}
int main(void) {
  /* the walker's input: yaw = (float)milli / 1000.0f, milli an Int */
  long n = 0, ds = 0, dc = 0;
  for (long m = -100000; m <= 100000; m++) {
    float a = (float)m / 1000.0f;
    float s1 = sinf(a), c1 = cosf(a);
    float s2 = (float)fsin_((double)a), c2 = (float)fcos_((double)a);
    n++; ds += (s1 != s2); dc += (c1 != c2);
  }
  printf("yaw milli -100000..100000: %ld inputs, sinf differs %ld (%.3f%%), cosf differs %ld (%.3f%%)\n",
         n, ds, 100.0 * ds / n, dc, 100.0 * dc / n);
  return 0;
}
