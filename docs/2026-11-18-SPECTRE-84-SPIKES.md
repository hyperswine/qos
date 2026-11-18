# Spectre-84: the four first spikes

Date: 2026-11-18. Kind: measurement record, milestone M0 of the plan to run
System.qa with a Shell.qa profile on Spectre-84, with device classes, a UART
host link and a software display (see [device classes](2026-11-18-DEVICE-CLASSES.md)).
Spectre-84 is the Tang Nano 20K with Simple-Risc's qualified fprisc-84
bitstream: RV32IM, CPU 84 MHz, SDRAM 48 MHz, 8 MiB.

Sources: QOS `4957161`, FP-RISC `e2dce0bd` (codegenRev 257), the fprisc-84
routed bitstream `output/tangnano20k/fprisc-84/impl/pnr/sdram_test.fs` (ROM
build id `28ed47fb2abb9afc`). Probe programs and scripts were scratch files;
their essential parts are quoted below.

**Verdict: go.** System.qa builds for RV32 unchanged and fits the 2 MiB SD
slot, the SD boot ROM can be patched into the qualified bitstream without a new
place and route, and the UART link's limits are now known. The one real
language-level hazard is time in a 31-bit Int.

## 1. System.qa for RV32

`--system=qos-native` pins rv64 (`fprisc/compiler/Compiler/CommandLine.hs:71`),
but options apply in order, so `--system=qos-native --target=rv32` already
selects RV32:

```
FPR_FOREIGN=core/foreign.fpr fpr compile --system=qos-native --target=rv32 \
  --prelude=<fprisc>/core/prelude.fpr programs/system.fpr system32.s
```

It compiles with no source change: 491 supercombinators in 28 module units,
linearity OK, 13.5 s. All units assemble for `rv32im_zicsr_zifencei`/`ilp32`.

| Part | RV32IM text |
|---|---|
| FP-RISC code (system.s and its units, before linking) | 1,363,316 B |
| Native C: runtime, virt machine layer, virt drivers, loader, sha256 (`-O2`, function sections, before linking) | 272,199 B (224,027 B bss) |
| Sum, before section garbage collection | about 1.64 MB |

The SD boot slot takes up to 2 MiB (`hal/spectre/actors/boot/rom.c`), so this
fits with about 0.4 MB to spare before linking removes unused sections. For
comparison the rv64 kernel `qos/qos/qos-native.elf` (with the C extension) is
987 KB text. The compiler's external symbol list for the kernel is the same
contract as rv64 (`Sys.placeImageAt`, `Sys.reservePid`, `reg32`, `device`, the
UART messages and so on).

## 2. The 31-bit Int audit

RV32 Int is a tagged 31-bit value with checked arithmetic (overflow panics).

- **Time is the real hazard.** `Sys.mtime` returns `TAG((sw)hal_mtime())`
  (`fprisc/runtime/actors.c:2675`). The virt and Spectre machine layers count a
  10 MHz timebase, so on RV32 the value is truncated and wraps every
  2^30 / 10^7 = 107 s, and the next subtraction across the wrap panics. This is
  the Spectre kernel's known uptime panic (`Int overflow: 1073741823 - -106585155`).
  System.qa reads time through `Sys.mtime` and the CLINT word directly
  (`programs/system.fpr:825`, `:1086`, "ticks / 10000000"). Fix in M5: a
  millisecond (or two-word) time primitive on 32-bit systems and its callers
  converted; µs would still wrap at 17.9 min.
- **QLog.** The chunk hash was already made RV32-safe (`hashByte`, split
  residue). `hCombine` (`programs/mods/qlog.fpr`, merkle nodes) multiplies a
  hash below 1e9+7 by 1,000,003, which overflows on RV32. Check whether any
  RV32 path reaches it, and split it the same way.
- **Timer.** `mods/timer.fpr:104` `Sys.sleepUs (ms * 1000)` overflows past
  about 17.9 minutes.
- **Literals above 2^30** in kernel modules: none. Outside the kernel:
  `scene2d.fpr:547-550` (three, needed by the display path in M8),
  `fprlive.fpr` (SHA constants), `appkit.fpr:99`, `runpolicy.fpr:6`.

## 3. The UART link on the board

The core's UART has a 32-byte receive FIFO and a 16-byte transmit FIFO (since
2026-10-12; `boards/tangnano20k/c/uart.h` still says one byte). The divisor is
fixed at 868, so the line runs at 96,774 baud at 84 MHz. Two probes ran on the
fprisc-84 image with an interrupt-filled 8 KiB receive ring:

**Echo** (host sends 4,096 random bytes, the board echoes):

| Host writes | Board received | Echo back on the host |
|---|---|---|
| 16, 64 or 255 B, no gap | 4096, no overrun | about 300-700 of 4096 |
| 16 B, 1 ms gaps | 4096 | 1120 in order |
| echo deferred until the host is silent | 4096 | 4096, no loss |

Host to board never lost a byte, even at full rate with no gaps. Board to host
never lost a byte while the host was silent. Loss happened only with the host
writing while the board transmitted, the Tang Nano's BL616 USB bridge.

**Stream** (the board sends a counting pattern continuously at full rate, the
host writes alongside; breaks counted in the pattern over 3 s, about 29,000
bytes received each run):

| Host writes | Breaks |
|---|---|
| silent | 0 |
| 1 B every 20-100 ms; 8 or 32 B every 100 ms | 0 |
| 8 B every 1 ms; 16 B every 2-3 ms; 24 B every 3 ms (4.4 KB/s) | 0-2 |
| 32 B every 5 ms | 10 |
| 48 B every 20 ms | 0; 64 B every 50 ms: 37 |
| 64 B every 5-20 ms; 255 B every 50 ms | 60-450, and the board's rate drops |

So the bridge drops board-to-host bytes when a single host write is large, not
when the host's rate is high. Writes of at most 24 bytes, at least 3 ms apart,
left a full-rate board stream intact. The board sends at the full line rate,
about 9.7 KB/s.

**For qlink:** board-to-host frames up to 255 bytes at line rate; host-to-board
frames split into writes of at most 24 bytes with a 3 ms gap (about 4 KB/s up,
plenty for input, files and control); a CRC and retransmission still guard
both directions. A received 0x03 resets the core outside the ROM, so framing
escapes it.

## 4. The SD boot ROM on the fprisc-84 bitstream

`spectre-image patchrom FS HEX ROM OUT` (`hal/spectre/tools/spectre-image.c`)
finds the ROM's 64 bit columns in a Gowin `.fs` by the original ROM contents
and rewrites only those columns and the affected frame CRCs. On the fprisc-84
`.fs` with its own stamped `bootrom-sdram.hex`:

- the ROM columns were found (frame row 1598, reversed, 64 matches);
- patching with the same ROM gave a byte-identical bitstream;
- patching with only the two build-id words changed altered 72 bytes, and the
  loaded bitstream answered `SRID1 isa=rv32im cpu=00000054 mem=00000030
  ram=00800000 max=00200000 cap=PMXQVHTUICG id=c0ffee845bec7e84`.

So Spectre-84 can take the SD boot ROM by patching the qualified bitstream,
keeping its timing closure; no place and route is needed. The build's guard
(`build-integrated.sol` checks one known bitstream hash) becomes an allow-list.
Remaining for M1: the ROM's SPI divisors for 84 MHz, a fallback to the UART
upload protocol when the SD slot is bad, and the fit in 508 words (today's SD
ROM is 1,475 bytes).
