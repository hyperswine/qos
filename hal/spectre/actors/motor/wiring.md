# Spectre pin 76 DC motor bench wiring

Revised 23 November 2026 for the parts on the bench: a BC550 NPN, a 1 kΩ
base resistor and a 1N5819 flyback diode. The first layout came from the
Infera planner, which then modelled Q1 as a two-terminal base-collector proxy
and put the emitter two strips away from the collector. A TO-92's three legs
sit in three adjacent holes, so a straight BC550 put its emitter in the pin 76
strip and the motor had no return to ground.

The planner ([motor76.nprolog](motor76.nprolog)) now knows three-leg TO-92
parts, axial parts whose legs are 1 to 4 columns apart with empty holes
under the body, and single-hole wires for off-board connections. The plan
below is its output, verbatim ([planner.txt](planner.txt)). Each column is
one connected five-hole strip, and row a is drawn at the bottom, nearest
you. On a larger board, use any five adjacent strips on one side of the
center gap.

```text
=== Breadboard, a–e side (row a nearest you) ===
     7    8    9   10   11   12   13
 e   ·    ·    ·    ·    ·    ·    ·
 d   ·    ·   GND   ·    ·    ·    ·
 c   ·    ·   GND   ·   M-   V+    ·
 b   ·   P76  Q1E  Q1B  Q1C  M+    ·
 a   ·   R1────────R1   D1A──D1K   ·
     7    8    9   10   11   12   13

=== Parts ===
  R1   1 kΩ    leg a8,  leg a10,  lying over the holes between
  D1   1N5819  anode a11,  cathode (striped end) a12,  stood on end
  Q1   BC550   Q1C b11,  Q1B b10,  Q1E b9   flat face toward row e (away from you)
  P76  b8      wire to FPGA pin 76
  M-   c11     wire to motor −
  M+   b12     wire to motor +
  V+   c12     wire to MB-V2 3.3 V (or 5 V if the motor is rated for it)
  GND  c9      wire to MB-V2 GND
  GND  d9      wire to Tang Nano GND

=== Strips (each column is one connected strip) ===
  8   PIN76      R1  a8    P76 b8
  9   GND        Q1E b9    GND c9    GND d9
  10  BASE       R1  a10   Q1B b10
  11  SWITCHED   D1A a11   Q1C b11   M-  c11
  12  MOTOR_VCC  D1K a12   M+  b12   V+  c12
```

- **Q1, BC550:** flat face toward row e, away from you. From your side you
  see its round back, and the legs from left to right are emitter, base
  and collector, in b9, b10 and b11. They go in straight.
- **Strip 9 is ground:** the emitter, MB-V2 GND and Tang Nano GND. The
  shared ground is required.
- **R1, 1 kΩ:** lies over a9 without touching it, which stays empty. Enough
  for a BC550: gain 200 to 800 needs well under 1 mA of base current for
  100 mA.
- **D1, 1N5819:** stands on end. The striped (cathode) end goes in a12,
  the motor + strip.
- **Strip 12 is the motor supply.** Use the MB-V2 3.3 V output, or 5 V if the
  motor is rated for it. The base drive stays 3.3 V either way. Keep the
  MB-V2 positive output off the FPGA's power pins.

Before powering anything, check that a meter on diode test reads about
0.6–0.7 V from base to emitter (b10 to b9) and from base to collector
(b10 to b11). Collector to emitter should be open in both directions.

**Limits:**

- **BC550 current:** 100 mA continuous, 500 mW. Many hobby DC motors draw
  more than that when starting or stalled. If the motor stutters, or the
  BC550 gets hot, use a part rated for the motor in the same holes:
  - a 2N2222A or S8050, rated 600 to 800 mA, with the base resistor
    lowered to 330 Ω. Check its pinout: many are E-B-C, which mirrors the
    order.
  - a logic-level N-MOSFET such as an AO3400 or IRLZ44N, with gate,
    drain and source in place of base, collector and emitter, about 100 Ω
    in series with the gate, and 10 kΩ from gate to ground.
- **Never connect the base to 3.3 V or pin 76 without the resistor.** Bare
  to 3.3 V can damage the transistor and load the MB-V2 regulator. From
  pin 76 it can damage the FPGA's output, which is set to an 8 mA drive.

**Bench checks** while `examples/tangnano20k_motor.fpr` runs:

1. Pin 76 (b8) to ground alternates between about 3.3 V and 0 V each
   second.
2. While it is on, the base (b10) reads about 0.7 V and the collector (b11)
   is near 0 V.
3. Shorting c11 to strip 9 by hand spins the motor. If it does not, the
   motor or its supply is the problem.

- [Netlist](netlist.csv), the planner's CSV output
- [Planner](motor76.nprolog) and its [output](planner.txt)

## Firmware-timed test

The experimental motor image replaces the servo PWM module at the existing
pin 76 MMIO endpoint with motor_gpio.v. A word write of 1 to 0x10001010 drives
the pin high. Other writes and FPGA reset drive it low. motor.c holds each
state for one second using the 84 MHz cycle counter, then drives low after
15 pairs. A firmware hang can leave the output high until FPGA reset.

The GPIO testbench passed. The experimental image routed, but its 84 MHz
timing check failed at -0.551 ns on a CPU pipeline register path. It was
not loaded and there is no physical motor result. The earlier hardware
cutoff variant also failed timing at -0.408 ns.

## Planned transistor test

Use Spectre-84 pin 76 to drive the BC550 low-side motor switch through the
1 kΩ base resistor, with the 1N5819 across the motor and a shared ground,
wired as above.
Load the pin 76 image (Simple-Risc `SDRAM_SERVO=1`, which passes 84 MHz;
see [README](README.md)) into FPGA SRAM and run fprisc's
`examples/tangnano20k_motor.fpr`: 15 pairs of one second on and one second off. Verify that the motor
starts and stops on each pair, the 3.3 V rail stays steady, and pin 76
finishes low. Record physical observations alongside the UART transcript.
The UART side of this run passed on 23 November. The motor did not spin
with the first layout.

## Bench results, 23 November 2026

What the user tried, and what happened:

| Circuit | Motor |
|---|---|
| Pin 76 through the 1 kΩ to the BC550 base, 1N5819 across the motor, FP-RISC motor program running | did not spin |
| Base through 1 kΩ to 3.3 V instead of pin 76 | did not spin |
| Base through 100 Ω to 3.3 V | did not spin |
| Base straight to 3.3 V, no resistor | spun (not a safe way to drive it: see Limits) |
| A push button in place of pin 76, with the BC550 and 1N5819 | did not spin |
| Motor, supply and a push button only, with no transistor or diode | spun |

The button tests leave out the FPGA and the program entirely. So the motor
and its supply work, and the fault is in the transistor and diode stage
itself, not in pin 76, the bitstream or FP-RISC. The cause is not yet
found. Candidates:

- the BC550 wired in the wrong orientation, or damaged by the
  no-resistor test
- the BC550's 100 mA rating being below what the motor needs to start
- the diode or a ground connection in the wrong strip

The meter check and bench checks above are the next step. It is not
recorded which layout, the first or this revised one, the button tests
used.

The planner started from NeoProlog's
[Infera breadboard planner example](https://github.com/hyperswine/NeoProlog/blob/main/examples/breadboard.nprolog).
[motor76.nprolog](motor76.nprolog) replaces its two-pin, adjacent-column
model with the footprints above and draws row a at the bottom.
