/* pins.c -- the virt pin bus (docs/PINS.md): QOS Native's GPIO tier.
 *
 * Was part of the compiler tree's hal/virt/hal.c.  A pin bus is a DEVICE, and
 * devices are the QOS HAL's: the machine layer under the language keeps only
 * what the runtime itself needs (boot, context switch, a console byte, the
 * doorbell and the timer, register access).  ../../docs/HAL.md. */
#include "fpr.h"

/* ---- GPIO pins (the C HAL tier; docs/PINS.md) -----------------------
 * A 32-pin bank with runtime-settable direction -- the portable
 * contract System.qa serves as /pins/<n> URLs.  THIS backend is the
 * QEMU-virt SIM: out-pin writes latch; an in-pin reads the latch of
 * whatever out-pin it is WIRED to (Pin.wire, the sim's test jumper --
 * how a matrix keypress is emulated with zero hardware).  A silicon
 * backend replaces these bodies with the target's GPIO MMIO; Pin.* is
 * the raw tier every pin service sits on. */
#define NPINS 32
static uint32_t pin_feed_pat[NPINS];
static uint8_t pin_feed_n[NPINS], pin_feed_i[NPINS];
#define PIN_TRACE_CAP 4096
static uint16_t pin_trace[PIN_TRACE_CAP];
static uw pin_trace_n;
static uint8_t pin_mode[NPINS];  /* 0 = in, 1 = out */
static uint32_t pin_out;         /* out latch */
static int8_t pin_src[NPINS];    /* sim wiring: in-pin n fed by out-pin pin_src[n], -1 = float(0) */
static int pins_inited;
static void pins_init(void) {
  if (pins_inited) return;
  for (int i = 0; i < NPINS; i++) pin_src[i] = -1;
  pins_inited = 1;
}
static V h_pin_mode(V nv, V mv) {
  pins_init();
  sw n = UNTAG(nv);
  if (n < 0 || n >= NPINS) fpr_cpanic("Pin.mode: pin out of range");
  pin_mode[n] = UNTAG(mv) ? 1 : 0;
  return (V)&fpr_unit;
}
static V h_pin_write(V nv, V vv) {
  pins_init();
  sw n = UNTAG(nv);
  if (n < 0 || n >= NPINS) fpr_cpanic("Pin.write: pin out of range");
  if (!pin_mode[n]) fpr_cpanic("Pin.write: pin is not an output (Pin.mode first)");
  if (UNTAG(vv)) pin_out |= (1u << n); else pin_out &= ~(1u << n);
  if (pin_trace_n < PIN_TRACE_CAP)
    pin_trace[pin_trace_n++] = (uint16_t)(n * 2 + (UNTAG(vv) ? 1 : 0));
  return (V)&fpr_unit;
}
static V h_pin_read(V nv) {
  pins_init();
  sw n = UNTAG(nv);
  if (n < 0 || n >= NPINS) fpr_cpanic("Pin.read: pin out of range");
  if (pin_mode[n]) return TAG((pin_out >> n) & 1); /* out: read back the latch */
  if (pin_feed_n[n]) { /* pattern stimulus: one bit per read, MSB first */
    int i = pin_feed_i[n];
    if (i < pin_feed_n[n]) pin_feed_i[n] = (uint8_t)(i + 1);
    return TAG((sw)((pin_feed_pat[n] >> (pin_feed_n[n] - 1 - (i < pin_feed_n[n] ? i : pin_feed_n[n] - 1))) & 1));
  }
  int s = pin_src[n];
  return TAG(s >= 0 ? (sw)((pin_out >> s) & 1) : 0);
}
/* SIM ONLY: feed an in-pin from a bit PATTERN, advancing one bit per
 * Pin.read -- the stimulus for serial slaves (a TTP229 answering its
 * 16 clocks, an SPI slave shifting a reply).  MSB first over nbits. */
static V h_pin_feed(V bv, V patv, V nv) {
  pins_init();
  sw b = UNTAG(bv);
  if (b < 0 || b >= NPINS) fpr_cpanic("Pin.feed: pin out of range");
  pin_feed_pat[b] = (uint32_t)UNTAG(patv);
  pin_feed_n[b] = (uint8_t)UNTAG(nv);
  pin_feed_i[b] = 0;
  return (V)&fpr_unit;
}
FPR_FN(fpr_g_Pin_x2efeed, h_pin_feed, 3);

static V h_pin_wire(V av, V bv) { /* SIM ONLY: out-pin a -> in-pin b (a<0 unwires) */
  pins_init();
  sw a = UNTAG(av), b = UNTAG(bv);
  if (b < 0 || b >= NPINS) fpr_cpanic("Pin.wire: dst out of range");
  pin_src[b] = (a >= 0 && a < NPINS) ? (int8_t)a : -1;
  return (V)&fpr_unit;
}
/* signal trace: every Pin.write records (pin, value) in order -- the
 * sim's logic analyzer.  Tests decode the captured WAVEFORM back into
 * protocol bytes (see tests/bbspi.fpr), which is how "are the signals
 * generally working" is answerable without silicon. */
static V h_pin_tclear(V d) { (void)d; pin_trace_n = 0; return (V)&fpr_unit; }
static V h_pin_tlen(V d) { (void)d; return TAG((sw)pin_trace_n); }
static V h_pin_tget(V iv) { /* 1-based; -> pin*2 + value */
  sw i = UNTAG(iv);
  if (i < 1 || (uw)i > pin_trace_n) fpr_cpanic("Pin.tget: index out of range");
  return TAG((sw)pin_trace[i - 1]);
}
FPR_FN(fpr_g_Pin_x2etclear, h_pin_tclear, 1);
FPR_FN(fpr_g_Pin_x2etlen, h_pin_tlen, 1);
FPR_FN(fpr_g_Pin_x2etget, h_pin_tget, 1);

FPR_FN(fpr_g_Pin_x2emode, h_pin_mode, 2);
FPR_FN(fpr_g_Pin_x2ewrite, h_pin_write, 2);
FPR_FN(fpr_g_Pin_x2eread, h_pin_read, 1);
FPR_FN(fpr_g_Pin_x2ewire, h_pin_wire, 2);
