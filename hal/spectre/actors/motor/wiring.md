# Spectre pin 76 DC motor bench wiring

Revised 23 November 2026 for the parts on the bench: a BC550 NPN, a 1 kΩ
base resistor and a 1N5819 flyback diode. The first layout came from the
Infera planner, which modelled Q1 as a two-terminal base-collector proxy and
put the emitter two strips away from the collector. A TO-92's three legs sit
in three adjacent holes, so a straight BC550 put its emitter in the pin 76
strip and the motor had no return to ground. In this layout the three legs
go into three adjacent strips in their real order.

Each column is one connected five-hole strip on the a–e side. On a larger
board, use any five adjacent strips on one side of the center gap.

```text
                     Breadboard strips on the a–e side
             8              9              10             11             12
 a       R1 leg 1 ───────────────────── R1 leg 2           ·              ·
 b           ·          Q1 C (left)    Q1 B (middle)   Q1 E (right)       ·
 c       FPGA pin 76     Motor −           ·           MB-V2 GND       Motor +
 d           ·          D1 anode ───────────────────────────────── D1 cathode (stripe)
 e           ·               ·             ·          Tang Nano GND    MB-V2 +
```

- **Q1, BC550:** flat face toward row e, legs down. From left to right the
  legs are collector, base and emitter, in b9, b10 and b11. They go in
  straight, with no bent leads.
- **R1, 1 kΩ:** a8 to a10, lying over strip 9 without touching it. Pin 76
  to the base. Enough for a BC550: gain 200 to 800 needs well under 1 mA of
  base current for 100 mA.
- **D1, 1N5819:** d9 to d12, stripe (cathode) at d12 on motor +. It lies
  over d10 and d11, which stay empty.
- **Strip 11 is ground:** emitter, MB-V2 GND and Tang Nano GND. The shared
  ground is required.
- **Strip 12 is the motor supply.** Use the MB-V2 3.3 V output, or 5 V if the
  motor is rated for it. The base drive stays 3.3 V either way. Keep the
  MB-V2 positive output off the FPGA's power pins.

Before powering anything, check that a meter on diode test reads about
0.6–0.7 V from base to emitter (b10 to b11) and from base to collector
(b10 to b9). Collector to emitter should be open in both directions.

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

1. Pin 76 (c8) to ground alternates between about 3.3 V and 0 V each
   second.
2. While it is on, the base (b10) reads about 0.7 V and the collector (b9)
   is near 0 V.
3. Shorting c9 to strip 11 by hand spins the motor. If it does not, the
   motor or its supply is the problem.

- [Complete netlist](netlist.csv)
- [Infera source](motor76.nprolog) and [planner output](planner.txt), for
  the first layout only. The planner has no three-terminal footprint, and
  this layout does not come from it.

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
with the first layout. This revised layout has not been tried yet.

The first placement used NeoProlog's
[Infera breadboard planner example](https://github.com/hyperswine/NeoProlog/blob/main/examples/breadboard.nprolog),
adapted in [motor76.nprolog](motor76.nprolog). The [netlist](netlist.csv)
now records the revised hand placement above.
