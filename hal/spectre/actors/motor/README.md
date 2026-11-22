# Pin 76 motor: current build path

As of 23 November 2026 the transistor motor test does not need its own
bitstream, so `motor_gpio.v` is superseded. Its image missed 84 MHz by
0.551 ns.

Simple-Risc's `servo_pwm.v` now has a level mode. On the
`SDRAM_PRESET=fprisc-84 SDRAM_SERVO=1` image, a word write of 1 to
0x10001010 drives pin 76 high at once and 0 drives it low. Widths from
1000 to 2000 µs still give servo PWM. That image closes 84 MHz at all four
placement options. See Simple-Risc `docs/2026-11-23-PIN76-MOTOR.md`.

The test itself is FP-RISC: fprisc `examples/tangnano20k_motor.fpr` over
`std/tangnano20k/pin76`. By default it runs 15 pairs of one second on and
one second off, and `--arg=PAIRS --arg=ON_MS --arg=OFF_MS` change that.
`motor.c` is the earlier C equivalent.

```sh
# in simple-risc
SDRAM_PRESET=fprisc-84 SDRAM_SERVO=1 SDRAM_OUT=/tmp/spectre-pin76 \
  boards/tangnano20k/sdram/build.sh
openFPGALoader -b tangnano20k /tmp/spectre-pin76/impl/pnr/sdram_test.fs
# in fprisc
./fpr sol machine/tangnano20k/examples.sol --program examples/tangnano20k_motor.fpr \
  --target board --preset fprisc-84 --fpga-manifest /tmp/spectre-pin76/build-manifest.json
```

The board run on 23 November completed all 15 pairs with the output left
off. Nobody watched the motor, so physical start and stop is still pending
at the bench. The wiring is in [wiring.md](wiring.md).
