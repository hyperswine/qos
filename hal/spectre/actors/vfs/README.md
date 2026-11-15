# Named QOS files on Spectre microSD

The client and filesystem are FP-RISC code. Actor 0 runs app.fpr and calls the
real std/fs append/readLatest message API. A spawned QLog interpreter owns a
direct block device registered by the Spectre HAL. QLog, not the SD driver,
chooses the metadata, record pages, file names and index. This is a standalone
composition of Files, not a test of namespace grants or a mounted desktop.

**Writer mode erases all 512 sectors** in a dedicated 64 x 4096 byte test
slice beginning at sector 131072. Only use it on disposable or explicitly
reserved media. This is not a partition discovery tool. The named file is
left on the card. Use --read-existing for subsequent non-destructive runs.
Reader mode never formats; the HAL refuses writes. Mount uses QLog buffered
v2 (flush reports unsupported). A warm reset is not a power-failure test.
The direct backend supports ordinary single-record reads and writes, not the
packed pair or asynchronous block-service paths. Do not use it as a general
storage service without implementing and testing the remaining operations.

Starting from the parent actor probe's scratch setup (../README.md):

    export QOS=/path/to/qos FPRISC=/path/to/fprisc SIMPLE_RISC=/path/to/simple-risc
    mkdir -p vfs
    cp "$QOS"/hal/spectre/actors/vfs/{app.fpr,hal.c,build.sh,run.py} vfs/
    (cd vfs && FPR_HOME="$QOS" FPR_PATH="$FPRISC" FPR_FOREIGN="$QOS/core/foreign.fpr" "$FPRISC/fpr" compile --target=rv32 --prelude="$FPRISC/core/prelude.fpr" app.fpr app.s)
    bash vfs/build.sh
    python3 vfs/run.py "$SIMPLE_RISC" vfs/fs.bin /dev/cu.usbserial-20250303171 --initialize-test-slice

The host checks ROM identity, CRC-verifies and starts the image, and selects
writer mode. It returns the CPU to the ROM with Ctrl-C, verifies/reloads the
executable and selects reader mode. Neither the filename nor the payload is
sent over UART. The successful read branch prints the bytes returned by Files.
A failed lookup on the second boot cannot silently recreate the file.

The first RV32 run in QEMU failed while hashing the payload: a signed tagged
Int could not represent the intermediate acc * 31. QLog now splits that
multiplication into two bounded terms without changing the polynomial or the
record format. This verifies the ordinary payload hash only; the wider
intermediate in the Merkle combine path is outside this probe's coverage.

Spectre's CLINT counts continuously through CPU reset. The adapter records a
boot epoch before starting the runtime. Otherwise the scheduler's language-level
Sys.mtime can return a negative tagged RV32 value on entry, breaking storage
deadline arithmetic. Starting the epoch at zero suffices for this short test;
it does not solve timestamp rollover for an always-running OS.

The full ELF payload can also be sent using a host-generated LZ4 boot wrapper
to shorten UART transfer. This is transport compression only. From vfs/:

    python3 pack.py
    riscv64-unknown-elf-gcc -nostdlib -mno-relax -march=rv32im_zifencei -mabi=ilp32 -Ttext=0x80000000 unpack.S -o packed.elf
    riscv64-unknown-elf-objcopy -j .text -O binary packed.elf packed.bin

Use packed.bin in place of fs.bin. This wrapper is only for a locally built,
CRC-verified image on the qualified 8 MiB SDRAM preset, not a general decoder.

**Physical pass, 15 November 2026.** ROM 9819062505a27795, 54 MHz RV32IMC,
runtime pin 566870c3; 845636-byte payload SHA-256
0b4f9da3545dfc56113586fdcc80b6198a82ad084936e5b829e68609ede08d5d.
The writer reported SAVED. After an independently observed return to ROM,
re-upload and read-only start, UART reported:

    READ hello from Spectre

This is the value returned by FS.readLatest for notes/spectre.txt. The file
was left on the card. It is not a cold-power or whole-OS boot test.
