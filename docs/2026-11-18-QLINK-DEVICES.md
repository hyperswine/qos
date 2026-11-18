# qlink devices: console, input, clock, host files and audio as classes

Date: 2026-11-18. Kind: implementation record, milestone M4 of the
Spectre-84 plan. Builds on [the console over qlink](2026-11-18-QLINK.md) and
the [session fixes](2026-11-18-MILLISECOND-DEADLINES.md). Sources: QOS after
`eefa7ff`, FP-RISC `b8a29c82`.

## What changed

**The console class (first commit of the milestone, `31d42f4`).** UART.qa
(`programs/mods/uart.fpr`) no longer touches registers: it drives a console
instance through `conOpen`, `conWrite`, `conRead`, `conArm`
(`hal/classes/console.{h,c}`). The 16550 code is one driver
(`hal/drivers/uart16550.c`) with pluggable register access, shared by QEMU
virt (MMIO) and Portable (its HAL table). System.qa spawns UART.qa on `con0`,
the instance the board manifest names. `UParams` (a divisor) is refused:
line settings are the driver's and the manifest's.

**Four more classes** (`hal/classes/{input,clock,hostfs,audio}.h`, primitives
in `hal/classes/devices.c`):

| Class | FP-RISC surface |
|---|---|
| input | `inRead d -> String` (4-byte events: kind, code, value) |
| clock | `clkNow d -> String` (epoch milliseconds in decimal; `""` unknown; epoch ms do not fit a 31-bit RV32 Int) |
| hostfs | `hfRead`, `hfList d path`, `hfWrite`, `hfAppend d path bytes -> Result String String` |
| audio | `audTone d freq ms -> Int` |

**qlink as a transport.** `hal/link/qlink_port.c` is a board's end of the
link over any byte-serial backend: session (HELLO nonce, BYE, ack loss),
channel demultiplexing, per-channel message reassembly (host frames carry
14 bytes), and flow control: a reliable frame the port has no room for is
refused, not acknowledged, and resent by the host, so nothing is dropped.
Backends: `qlink_sruart.c` (Simple-Risc's UART; also the boot HAL's
`qcon_*` console) and `qlink_uart16550.c` (QEMU virt's UART0).
`hal/drivers/qlink_dev.c` provides all five classes on a port; a board names
each instance in its manifest with the port it rides:

    {"name": "clk0", "driver": "qlink_clock", "params": {"port": "&qlink_board_port", "init": "0"}}

`init` starts the port on first use where the board has no boot hook (virt).
`bsp/spectre84` gains `con0`, `in0`, `clk0`, `hf0`, `aud0` (in
`SPECTRE_CONSOLE=qlink` builds); the new `bsp/virt-qlink` is QEMU virt with
UART0 carrying qlink and the same five instances.

**tools/qhost serves the channels.** The clock (epoch ms after HELLO and
every minute), host files under `--root DIR` (relative paths only, no `..`,
nothing resolving outside the root; without `--root` every request is
refused), audio (reported on stderr, played with `afplay`/`aplay` when
present). New script steps `send` (escapes), `key CODE`, `expect-tone`; new
`--wait` for slow-booting guests; SIGPIPE ignored.

**qlink core:** `deliver` may refuse a reliable frame (`stats.refused`).

## Checks

- `tools/qhost/qlink_test.c`: all reliable messages arrive once and in order
  over lossy and corrupting wires and with a receiver that refuses 30% (and
  10% with loss and corruption) of frames.
- `tools/qlink-qemu-check.sol` (new), on QEMU virt-qlink with two harts:
  **devices** (`tests/qlinkdevs.fpr`: host clock, host file read and write,
  `../outside` refused, a tone, a key press and release) and **system**
  (System.qa with `con0` on qlink: the four permission prompts answered
  through qhost, then the TUI app launcher draws). Both pass.
- Spectre-84 (SD boot, FP-RISC `b8a29c82`), through qhost on the board's
  UART: `date` (the host's epoch ms), `hcat` and `hls` of host files, `hput`
  (the file appears on the host with the right contents), `hcat ../etc/passwd`
  refused, `beep` (a tone on the host), `keys 2` (key 30 down and up), and
  `ls` of the SD QLog afterwards.
- Regressions: the five QEMU virt native fixtures, Portable `uartsvc`,
  `uartroute`, `svcurl`, `kbdread` (same output as before) and
  `storagedeadlines`, and the raw-console Spectre build.

## Findings on the way

- **An interrupt-driven console writer stranded its last bytes.** UART.qa
  hands bytes to the class and then waits for interrupts; bytes still in
  the port's line buffer went out only on the next write, so System.qa's
  prompt stopped at "grant ". The port's poll now sends the buffer whenever
  the window has room.
- **System.qa's permission prompts read one key per answer.** A script that
  sends `y\n` answers the next prompt with the newline; `qhost send y` does
  what a person at a terminal does.
- **System.qa needs two harts** (`-smp 1` boots silently), which the
  fixtures already used.
- **FP-RISC `print` from a native kernel does not reach UART0 raw** the way
  the C HAL's boot lines do; the device check reports through `con0`.

## Not done in this step

Portable implements the console class but not input, clock, hostfs or
audio (it has its own input and sound primitives; generating its HAL
members per class is the plan's last step). UART.qa over qlink relies on
received bytes (acknowledgements) to wake it for transmit progress; a lost
acknowledgement waits for the next received byte. The display class and
software renderer are M8.
