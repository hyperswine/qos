# System.qa on Spectre-84, and the memory it took

Date: 2026-11-19. Kind: implementation record, milestone M6 of the
Spectre-84 plan (first part: System.qa as the SD image; process images on
the board and the power-cycle check are still to do). Sources: QOS after
`5a23e75`, FP-RISC `0230c8f1`.

## Result

System.qa runs on the Tang Nano 20K with the fprisc-84 bitstream: it boots
from the SD card, opens the SD QLog ("storage: disk online -- boot #1"),
takes the four permission answers through tools/qhost over qlink, and draws
the TUI app launcher. Left in the launcher for more than three minutes its
clock kept time, and a key then moved the selection. The image is 1.50 MB
(525 KB packed), inside the 2 MiB SD slot.

    SPECTRE_BOARD=spectre-84 SPECTRE_CONSOLE=qlink SPECTRE_IMAGE=system \
      sol hal/spectre/actors/boot/build-integrated.sol OUT
    qhost script PORT --mhz 84 --wait 40 expect "keyboard (read) ?" 90 send y ...

## The image

- `SPECTRE_IMAGE=system` (`boot/build-integrated.sol`) compiles
  `programs/system.fpr` for qos-native RV32, links it with spectre-build's new
  `system` target and makes it the SD image in place of the boot shell.
- `hal/spectre/actors/system/hal.c`: boot, the 10 MHz timebase over
  Simple-Risc's cycle-counting CLINT, and `hal_putc` writing raw (outside
  qlink frames, so boot lines and panics reach qhost with or without a
  session). The rest is shared with QEMU: fprisc's virt machine layer, QOS's
  RV32 PLIC driver (Simple-Risc's CLINT and PLIC have virt's layout for hart
  0), and the loader, lifecycle and placeholder app registry.
- `bsp/spectre84`: `blk` (SD over SPI), `net` (new `hal/drivers/nonet.c`:
  every net primitive fails the caller with "net: NIC absent", as virtio-net
  does without a NIC, with `net_actor_bridge.c` for the owner primitives),
  and con0, in0, clk0, hf0, aud0 on qlink.
- The qlink backend gained its receive-interrupt hook (UART CTRL bit 0), so
  UART.qa on con0 is woken by PLIC source 10.
- `sd_spi.c` provides `blkPackPair` (it was a panicking stub in the Spectre
  images) and answers the virtio-only budget primitives honestly: no budget
  (version 0), any budget refused as invalid.
- qlink keeps console output written while no host is attached in a 4 KiB
  backlog and replays it when a session opens, after a line counting any
  bytes that did not fit; without it the permission prompts were lost before
  anyone could attach.
- One hart: `HARTS=1` (System.qa had needed two only because the build
  default was 2).

## The memory

On QEMU with Spectre's memory map (a heap of about 6.3 MiB), System.qa ran out
of memory at boot. Instrumenting the allocator found four causes:

1. **Big-machine sizes.** The runtime's buddy blocks are at least 64 KiB, an
   actor's first stack is 128 KiB and slabs grow to 256 KiB: about 96 blocks
   in 6 MiB. A 64 KiB slab plus the buddy's header took a 128 KiB block.
   The Spectre `system` build now compiles with 4 KiB blocks, 16 KiB first
   stacks (they grow on demand), and slabs of 4 KiB - 8 to 32 KiB - 8 and
   16 KiB - 8 message slabs (all existing FP-RISC build switches).
2. **UART.qa kept every turn's garbage (all platforms).** It looped by
   hand-written receive recursion, and each `UGet` turn built a new state
   record and reply that were never reclaimed: about 100 KB/s on an idle
   System.qa, rv64 included (measured on the tree before the console class
   too). It now runs as `Sys.loop`, whose per-turn arena is rewound. uart
   v5.0 `3eedf3bc88217cb1`, pinned by sysep.
3. **The keyboard endpoint polled UART.qa every millisecond** while a read
   was held (for Portable, which has no receive interrupt) and was also a
   hand-written recursion. It runs as `Sys.loop` now (pushes reach it as
   request-shaped tuples from sender 0, so its turn reads one message
   type) and polls every 20 ms.
4. **The network service polled every millisecond with nothing to pump**
   (about 2 MB/s of allocation and freeing). It blocks in `receive` unless
   it has frames to pump. std/net v5.0 `0e7c699bca3ce421`.

The launcher polled the keyboard and clock endpoints every millisecond; their
replies' message slabs are released only in batches (about every two
minutes), so at that rate they piled up faster than they came back. It polls
every 20 ms now. With all of it, System.qa in QEMU's 8 MiB map holds a
bounded sawtooth for five minutes (free memory between 3.9 and 4.7 MB), and
idle memory on the 128 MiB map no longer falls at all (it fell about 92 KB/s).

## Checks

- Spectre-84 board: boot from SD, storage online, prompts answered over
  qlink, launcher drawn, three minutes in the launcher, a key handled.
- QEMU virt32, one hart, Spectre's 8 MiB map with the small-memory profile:
  five minutes bounded (above).
- Regressions: `tools/qlink-qemu-check.sol` (devices, System.qa launcher over
  qlink), the five rv64 native fixtures, `tools/native-image-check.sol` rv32
  and rv64, Portable `uartsvc`, `uartroute`, `svcurl`, `kbdread` (its
  FAILED line identical to before), `timer`, `timerroute`,
  `storagedeadlines`, `filessvc`, `appjobs`.

## Open

- **Message slabs released in batches.** Reply slabs from endpoints polled at
  1 kHz were held for minutes before release; the cause is in FP-RISC's
  message-slab lifetime (receives inside `Sys.arena` within a `Sys.loopWith`
  step) and needs its own investigation. The launcher's 20 ms poll keeps it
  bounded on 8 MiB.
- **Hand-written receive loops.** UART.qa and the keyboard were converted;
  other long-lived QOS services that loop by hand-written recursion and
  allocate per turn would leak the same way.
- **Process images on Spectre-84** (the M5 gate on the board): rv32im
  images, built with the Spectre kernel's flags, loaded from the SD QLog.
- **Power-cycle boot**: a power cycle reloads the flash bitstream (54 MHz),
  so the cold check needs fprisc-84 written to flash, which needs the
  owner's go-ahead.
- The SD QLog volume is the boot shell's 64 pages (256 KiB).
