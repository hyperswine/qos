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
