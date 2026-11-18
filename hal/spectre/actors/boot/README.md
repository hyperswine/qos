# Spectre 54 MHz SD boot demonstrator

## Integrated image and board checks

From the QOS checkout, with sibling fprisc and simple-risc checkouts, run:

    sol hal/spectre/actors/boot/build-integrated.sol /tmp/spectre-build

Choose an output directory that does not exist yet. FPRISC and SIMPLE_RISC
may override the sibling paths. The build needs the FP-RISC host compiler
at fprisc/fpr, the QOS module store, RV32-capable riscv64-unknown-elf tools,
Bash, Git, Python 3, shasum and liblz4. The board input is the qualified
btbdef-54 routed bitstream and matching bootrom-sdram.hex under the Simple-Risc
output directory. The ROM patcher verifies the routed bitstream's hash.
The runtime comes from fprisc.lock.json and the board C/startup sources from
the board revision in the build script. The host compiler and QOS sources
come from the supplied checkouts. Preserve those inputs and the toolchain
to reproduce a particular build.

SHA256SUMS covers the kernel, SD boot-slot image, UART installer, patched
FPGA image and five separately built applications. Compare manifests from
two fresh directories to check repeatability. The build never opens the board.
The following bring-up notes describe installation on the existing Spectre
test volume. The qualification checks expect notes/spectre.txt on that volume.

With the installer verified and the shell running, export SIMPLE_RISC to
the full board checkout and run these commands from the output's boot directory:

    sol "$QOS"/hal/spectre/actors/boot/check-writable.sol warm
    sol "$QOS"/hal/spectre/actors/boot/check-writable.sol cold
    (cd apps && sol "$QOS"/hal/spectre/actors/boot/apps/check-two.sol && sol "$QOS"/hal/spectre/actors/boot/apps/check-two.sol --mailbox)

The checks drive the prompt through `spectre-uart` (hal/spectre/tools/spectre-uart.c;
SPECTRE_UART_TOOL names the built helper, SPECTRE_UART the port).

After the cold checker prints armed, remove all board power for five seconds
with the microSD inserted, then reconnect. The checker observes USB removal
and reconnection, listens for the SD boot marker and prompt, then verifies
the exact file created before power loss. The app checks verify their named
images and use apps/hello2.sxa for the freshly compiled hello fixture.

## Spectre-84 (18 November 2026)

`SPECTRE_BOARD=spectre-84` builds the same image for Simple-Risc's qualified
fprisc-84 bitstream (RV32IM, CPU 84 MHz, SDRAM 48 MHz): the board C gets
`-DCORE_MHZ=84`, the ROM and installer use the second boot slot at LBA 139264
(the 54 MHz kernel stays at 135168, so one card holds both), and the ROM is
patched into `output/tangnano20k/fprisc-84` (its hash is on the build's list).
`SPECTRE_RUNTIME_REV` overrides the runtime revision from `fprisc.lock.json`;
the lock predates FP-RISC's RV32 raw-mask fix, so name a later revision. The
tools take the clock from `SPECTRE_MHZ` (default 54); the UART runs at
round(MHz * 1e6 / 868) = 96774 baud at 84 MHz.

    SPECTRE_BOARD=spectre-84 SPECTRE_RUNTIME_REV=<fprisc rev> \
      sol hal/spectre/actors/boot/build-integrated.sol /tmp/spectre-84
    SPECTRE_MHZ=84 spectre-uart PORT upload boot/install.bin 120 1 expect DONE 120
    openFPGALoader -b tangnano20k --ftdi-serial 2025030317 boot/patched-pre.fs

Board run, 18 November 2026 (FP-RISC runtime e2dce0bd, from SRAM): the
installer wrote and compared slot 139264, the patched bitstream booted from SD
to `qos>`, `ls` listed the existing volume, and with `SPECTRE_MHZ=84`
`check-writable.sol warm`, `check-two.sol` and `check-two.sol --mailbox` passed.
The cold check needs the patched bitstream in configuration flash, which still
holds the 54 MHz image; it was not run.

## Original boot bring-up

The CPU reset ROM initializes an SDHC/SDXC card over SPI and validates a
little-endian 12-byte header (magic 0x31544253, byte length up to 2 MiB,
IEEE CRC32) at LBA 135168. The executable starts at the next sector. The ROM
loads it to 0x80000000, checks CRC and jumps. The packed executable unpacks
into SDRAM and starts the QOS scheduler and QLog. CPU reset now goes to SD,
not the UART uploader. Recovery is by JTAG. The first filesystem slice remains
at LBA 131072..131583; the installer never writes there. The prompt supports
one command, cat NAME, resolved through FS.readLatest against a read-only HAL.

This board trial reused the qualified 54 MHz routed design. The build checks
the SHA-256 of the known original .fs, and `spectre-image patchrom`
(hal/spectre/tools/spectre-image.c) finds each of the 64 ROM bit columns
against all 512 original words using the Gowin BSRAM initialization mapping,
and replaces those columns and their affected frame CRCs only. No logic or
routing changes. This is specific to that exact uncompressed board build.
The old bitstream user-code metadata is not an identity for the new ROM.

Build inputs: the actor probe's pinned RV32 runtime scratch build, QOS's
std/fs, the wake-tested 54 MHz board, and Simple-Risc's sd.c/bootrom startup.
For the app, follow ../vfs/README.md using boot/ instead of vfs/ and this
directory's app.fpr and hal.c (target `boot` of ../build.sol). Pack the payload with
`spectre-image lz4` and the VFS probe's unpack.S. Header and payload are installed with the one-time UART
installer; the header is written last after each payload sector was compared.
Normal boots need neither this installer nor a host image. UART is a console.
The prompt is a bring-up tool, not a multiuser shell. CRC checks accidental
corruption; it does not authenticate executable code.

Preparation (one time): run build-integrated.sol, which compiles boot/app.fpr,
links boot/fs.bin and builds the media, the patched bitstream and install.bin. With the original
UART ROM active, upload install.bin at 54 MHz through the guarded protocol.
Require the SD readback comparison before changing FPGA configuration. Test
patched-pre.fs in SRAM first. A serial terminal on the FPGA UART uses
round(54000000 / 868) = 62212 baud, 8N1. The command is:

    qos> cat notes/spectre.txt

Board trial, 15 November 2026: ROM is 1475 bytes. The installer compared the
boot slot, the volatile FPGA run booted from SD and returned hello from Spectre,
and the W25Q64 configuration flash was backed up before programming and
readback verification. Candidate bitstream SHA-256:
7782fd5d8a751ed90e70f35764b63ff86efeb1f155dc398cc4add2c266ebaa26.

Physical cold boot passed after five seconds without power. USB disappearance
and re-enumeration were observed. No JTAG or UART upload and no boot command
were issued on reconnection. The serial observer received the boot marker and
prompt before sending the command. Actual transcript:

    Spectre SD boot OK
    qos> cat notes/spectre.txt
    hello from Spectre
    qos>

## Writable prompt (15 November 2026)

The updated SD application mounts the existing volume in place without
formatting it. The FPGA boot ROM is unchanged. The current commands are:

    create NAME TEXT     create a new named file; reject an existing name
    ls                   list the live QLog names
    cat NAME             print the latest stored contents

Names are single tokens. Text can contain spaces. The serial reader accepts
up to 256 printable ASCII characters per line. For automation on this
polled UART, pace characters (the acceptance harness uses 5 ms per byte);
a long paste can overrun the receiver without reporting a transport error.
Create checks absence before append; this is a single-shell composition,
not an exclusive-create guarantee for concurrent clients. Listing enumerates
the real live index, suppressing repeated names. This owner-only request
is not a namespace-wide grant. This volume retains native buffered v2
semantics; power loss in the middle of an append is not tested.
