#include "uart.h"
static volatile uint32_t *const motor = (volatile uint32_t *)0x10001010u;
static uint32_t cycles(void) {
    uint32_t value;
    __asm__ volatile("csrr %0, mcycle" : "=r"(value));
    return value;
}
static void second(void) {
    uint32_t start = cycles();
    while (cycles() - start < 84000000u) {}
}
int main(void) {
    *motor = 0;
    for (unsigned pair = 0; pair < 15; ++pair) {
        uart_puts("motor on\n");
        *motor = 1;
        second();
        *motor = 0;
        uart_puts("motor off\n");
        second();
    }
    uart_puts("motor output disabled\nDONE");
    for (;;) {}
}
