# Spectre pin 76 DC motor bench wiring

The Infera breadboard planner placed the 1 kΩ base resistor, 1N5819
flyback diode and Q1 base/collector on the a–e half of the 170-tie model.
Each column below is one connected five-hole strip. On a larger board,
use any five adjacent strips on one side of the center gap.

```text
                    Breadboard strips on the a–e side
             8              9           10             11           12
 a       RBASE.1 ─────── RBASE.2      D1 anode ──── D1 cathode      ·
 b           ·           Q1 base     Q1 collector      ·      Q1 emitter
 c       FPGA pin 76         ·       Motor −        Motor +     MB-V2 GND
 d           ·               ·           ·          MB-V2 3.3 V Tang Nano GND
 e           ·               ·           ·             ·           ·
                                     The stripe on D1 faces strip 11.
```

Q1 is an NPN low-side switch. The planner models two-terminal footprints.
The Q1 B/C entry is a placement proxy. Strip 12 and the external wires
were added to the planner placement. Check the exact transistor pinout
and use short leads or jumpers to reach the assigned holes. The diagram
specifies electrical terminals and does not dictate the package orientation.
Use the verified MB-V2 3.3 V and GND output pins for the motor, and keep
the MB-V2 positive output separate from the FPGA's power rails.

- [Complete netlist](netlist.csv)
- [Infera source](motor76.nprolog)
- [Planner output](planner.txt)

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
