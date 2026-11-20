#ifndef SPECTRE_SERVO_H
#define SPECTRE_SERVO_H

/* The servo-enabled bitstream supplies this register. Zero disables output. */
static V spectre_servo_set_pulse_us(V pulse) {
    if (!ISINT(pulse)) return TAG(0);
    int us = UNTAG(pulse);
    if (us != 0 && (us < 1000 || us > 2000)) return TAG(0);
#ifdef SPECTRE_SERVO_MMIO
    *(volatile uint32_t *)(uintptr_t)SPECTRE_SERVO_MMIO = (uint32_t)us;
    return TAG(1);
#else
    return TAG(0);
#endif
}
FPR_FN(fpr_g_spectreServoSetPulseUs, spectre_servo_set_pulse_us, 1);

#endif
