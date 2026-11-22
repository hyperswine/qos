# Spectre-84 header allocation and Servo SDK proposal

The table lists connector contacts on the Tang Nano 20K revision 3921.
Numbers in the FPGA columns are package pins. The two columns describe
separate connectors. Check the board revision and connector orientation
against the [Sipeed schematic](https://dl.sipeed.com/fileList/TANG/Nano_20K/2_Schematic/Tang_Nano_20K_3921_Schematics.pdf).

| Contact | J5 FPGA or rail | J5 allocation | J6 FPGA or rail | J6 allocation |
|---:|---|---|---|---|
| 1 | 5V | Power | 73 | Reserve USB bridge HSPI |
| 2 | GND | Ground | 74 | Reserve USB bridge HSPI |
| 3 | 76 | Servo PWM on servo build, shared with bridge HSPI | 75 | Reserve USB bridge HSPI |
| 4 | 80 | microSD | 85 | microSD |
| 5 | 42 | GPIO candidate, shared LCD | 77 | GPIO candidate, shared LCD clock |
| 6 | 41 | GPIO candidate, shared LCD | 15 | Onboard LED |
| 7 | 56 | Reserve audio | 16 | Onboard LED |
| 8 | 54 | Reserve audio | 27 | GPIO candidate, shared LCD |
| 9 | 51 | Reserve audio enable | 28 | GPIO candidate, shared LCD |
| 10 | 48 | GPIO candidate, shared LCD DE | 25 | GPIO candidate, shared LCD |
| 11 | 55 | Reserve audio | 26 | GPIO candidate, shared LCD |
| 12 | 49 | Reserve LCD backlight | 29 | GPIO candidate, shared LCD |
| 13 | 86 | Reserve USB bridge HSPI | 30 | GPIO candidate, shared LCD |
| 14 | 79 | Onboard WS2812 | 31 | GPIO candidate, shared LCD |
| 15 | GND | Ground | 17 | Onboard LED |
| 16 | 3V3 | Power | 18 | Onboard LED |
| 17 | 72 | Reserve USB bridge HSPI | 19 | Onboard LED |
| 18 | 71 | Reserve USB bridge HSPI | 20 | Onboard LED |
| 19 | 53 | Reserve display EDID | 3V3 | Power |
| 20 | 52 | Reserve display EDID | GND | Ground |

## GPIO and PWM routing at runtime

The FPGA constraints bind GPIO lines to physical package pins and set their
electrical mode. The bitstream exposes a fixed GPIO bank. Start with the
ten LCD-shared candidates when the build leaves their LCD functions free.
Keep microSD, UART and other reserved signals outside the bank. Pin 76 can
join the bank after checking USB bridge HSPI ownership for that board and
build. The existing servo test used a dedicated PWM output on pin 76.

Expose input, output latch and output-enable registers. Reset each line to
input with its output driver disabled. Load the output latch before enabling
an output. FP-RISC apps can request access to an allowed line through QOS
and change its direction and output value at runtime.

Add an FPGA mux on PWM-eligible lines to select GPIO or a hardware PWM
channel. QOS owns the mux and the line lease. A line has one owner and
one function at a time. Reject pins outside the BSP allowlist and changes
that conflict with an active lease. Disable output before routing PWM to
another line, then enable the new output at a frame boundary. The hardware
PWM counter continues to generate pulses independently of app scheduling.
Qualify GPIO reads and writes with loopback, and verify PWM routing and
disable behavior on the board before publishing a supported pin list.

## Servo service for the next SDK release

Expose a QOS device service for hardware PWM and a small SDK Servo client.
Use a logical channel name in the app manifest. The BSP maps that name
to a PWM channel and an eligible GPIO line. The first target configuration
maps `lift` to one channel routed to package pin 76. Both servo signal
inputs can share that channel, as in the lift test. An authorized board
configuration can remap `lift` among eligible pins at runtime. The app
keeps using the same name. The initial pin bank and which lines have a PWM
mux remain bitstream properties.

| Proposed client operation | Result |
|---|---|
| Open a named channel | Exclusive lease or unavailable, denied or busy |
| Set pulse width in microseconds | Accept 1000 through 2000 and apply at next frame boundary |
| Disable | Schedule output low at next frame boundary |
| Close | Disable and release the lease |

Keep the MMIO write in the privileged driver. Report success as acceptance
of a command. Physical position feedback is outside this API. On stop,
disconnect or app death, the device owner disables the channel before
granting a new lease, and returns the pin to input when the lease ends. Use the existing 20 ms frame in the first release.

The servo variant currently selects PWM at bitstream build time and the HAL
uses a separate compile-time MMIO define. Add an explicit board capability
identifier and keep the stock build's service unavailable. Qualify wrong
image and invalid width handling, ownership refusal, stop and lease reuse,
and an independently packaged RV32 SDK demo launched from microSD. Then
place the demo in spectre-84-playground and publish the matching QOS,
FP-RISC and Simple-Risc revisions.

The [servo qualification notes](../hal/spectre/actors/servo/README.md)
record the physical single-channel and tandem runs. GPIO and the SDK service
above are proposed allocations and interfaces.
