# SG90 on Spectre-84

The experimental Spectre-84 image assigns the servo signal to FPGA package
pin 76 and maps a 32-bit pulse-width write to 0x10001010. Build the image
from Simple-Risc into a separate output directory:

```sh
SDRAM_PRESET=fprisc-84 SDRAM_SERVO=1 SDRAM_OUT=/tmp/spectre-servo84 \
  boards/tangnano20k/sdram/build.sh
```

Configure the HAL build with `-DSPECTRE_SERVO_MMIO=0x10001010u` when using
that image. The FP-RISC foreign symbol is `spectreServoSetPulseUs` with
signature `unsafe Int -> Int`. Its return value is 1 for an accepted write
and 0 for an unsupported or invalid command. Zero schedules disable, and
1000–2000 schedules that many microseconds high each 20 ms frame. The RTL
latches the next pulse width at the frame boundary.

The standalone UART probe uses the same HAL function and exercises
1500, 1400, 1600, 1500 and zero microseconds. From this directory, with
QOS, FPRISC and SIMPLE_RISC set to their checkouts:

```sh
board="$SIMPLE_RISC/boards/tangnano20k"
riscv64-unknown-elf-gcc -march=rv32im_zicsr -mabi=ilp32 -Os -ffreestanding \
  -nostdlib -ffunction-sections -fdata-sections -Wl,--gc-sections \
  -I"$board/c" -I"$FPRISC/runtime" -I"$QOS/hal/spectre/actors" \
  -T "$board/sdram/link.ld" "$board/c/crt0.S" "$board/c/uart.c" \
  board-servo.c -lgcc -o board-servo.elf
riscv64-unknown-elf-objcopy -O binary board-servo.elf board-servo.bin
```

Load the timing-checked bitstream to FPGA SRAM. Use the ROM's guarded UART
upload at 84 MHz for the probe. UART confirms the program progressed through
the register writes. Measure the pin or observe the horn to verify the output.

## Physical result, 20 November 2026

On the Tang Nano 20K, the SG90 signal was connected to FPGA pin 76.
The servo-enabled Spectre-84 bitstream passed the internal 84 MHz timing
check and was loaded into FPGA SRAM. The UART probe reported pulse widths of
1500, 1400, 1600 and 1500 microseconds, then commanded zero to disable the
output. The user observed the servo move and return to its starting position.
The observation confirms physical movement. Pulse widths were verified in
simulation, and the board run recorded the HAL commands in [board.log](board.log).

## One-minute randomized test

The SG90 on FPGA pin 76 completed a 60-second test with 22 alternating
position commands at 1400 and 1600 microseconds. The probe randomized the
intervals and disabled PWM between moves. The user observed consistent
movement in both directions throughout the run. The board reported DONE
with PWM disabled. See the [UART transcript](minute-board.log).

## Loaded mechanism tests, 21 November 2026

Three 60-second runs each alternated 1400 and 1600 microsecond commands
once per second. Two runs used the rack-and-pinion assembly and one used
the lead-screw assembly. The user confirmed the rack-and-pinion completed
its strokes under load and the lead screw moved smoothly in both directions.
All three UART logs show 60 commands followed by PWM disable and DONE.

Across the initial movement check, randomized test and loaded runs, no board
crashes, resets or signs of underpower were reported. This is observed
behavior for the tested setups. Supply voltage and current were not measured.

UART logs: [rack-and-pinion](alternate-board.log),
[repeat](alternate-repeat.log), [lead screw](leadscrew-board.log).

## CoScad dual-SG90 lift test, 21 November 2026

Two externally powered SG90s shared the Spectre-84 PWM signal on FPGA pin 76
and drove the CoScad lift. The one-minute test alternated 1400 and 1600
microsecond commands once per second. UART recorded all 60 commands, PWM
disable and DONE.

The user confirmed that the lift worked and reported no problems with the
core setup. Some asymmetry developed over time. Servo synchronization or
mechanical differences were suspected. The test did not identify the cause.

[UART transcript](tandem-external.log)

## Revised CoScad 2-lift, 22 November 2026

The new 2-lift places the lead screws halfway along their respective edges.
The user reported less static imbalance than with the previous layout.
Some imbalance remained during motion. The left servo appeared to move
slightly faster than the other, which is a possible cause. Individual servo
speeds were not measured.

The same one-minute shared-PWM test completed 30 round trips. UART recorded
all 60 commands and confirmed PWM disable. See the [UART transcript](tandem-symmetry.log).

## Single-servo fault isolation, 22 November 2026

One of four servos was confirmed working by the user after swapping it
back in. It moved like it did in the original test and now has a sticker
on it for identification. The other three remain suspect:

- One stayed silent and stationary. The MB-V2 LED dimmed when its power
  leads were connected. [30-second diagnostic](diagnostic-board.log)
- One made an internal gear or mechanism buzz without visible output
  motion. [One-minute retest](rack-regime-retest.log)
- The replacement stayed stationary and the MB-V2 LED dimmed.
  [Replacement test](replacement-rack.log)

UART confirmed the programmed command sequences and final PWM disable
on the three logged runs. The observed symptoms leave power delivery,
wiring, and internal servo faults as possible causes. The user had
previously identified 9 V adapters in the four-servo setup, so overvoltage
damage is also possible. No internal failure was confirmed.

### Final single-servo check

Two servos are now confirmed working and are marked with **W** stickers.
The other units are marked **X**. The final servo moved normally throughout
the one-minute test. UART recorded all 60 alternating commands and the final
PWM disable. [Final test transcript](final-servo.log)

The user reported varied symptoms among the X units in the same test setup,
including no movement, internal buzzing, and the MB-V2 indicator dimming.
One suspect unit was new and had never been connected during the four-servo
test. The earlier 9 V supply mix-up may have affected some units from that
test. The cause of each unit's symptoms remains unconfirmed.
