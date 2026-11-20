#include "uart.h"
#include "fpr.h"
#define SPECTRE_SERVO_MMIO 0x10001010u
#include "servo.h"

static uint32_t cycle(void) {
    uint32_t now;
    __asm__ volatile("csrr %0, mcycle" : "=r"(now));
    return now;
}

int main(void) {
    static const unsigned widths[] = {1500, 1400, 1600, 1500, 0};
    for (unsigned i = 0; i < sizeof widths / sizeof widths[0]; ++i) {
        if (spectre_servo_set_pulse_us(TAG(widths[i])) != TAG(1)) {
            uart_puts("servo HAL rejected pulse\nDONE");
            return 1;
        }
        uart_puts("servo pulse width (us): ");
        uart_put_uint(widths[i]);
        uart_putc('\n');
        uint32_t start = cycle();
        while (cycle() - start < 84000000u) {}
    }
    uart_puts("servo output disabled\nDONE");
    for (;;) {}
}
