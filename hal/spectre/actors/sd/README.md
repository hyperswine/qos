# Spectre microSD actor reset probe

A spawned native actor owns the Simple-Risc SPI card driver (PIO, divider 15).
The only accessible LBA is 131072, the existing board test location. This is
a raw-sector test, **not** a filesystem operation: only run on a card whose
owner has designated that sector disposable. The host first reads and saves
its contents, then sends a fresh 512-byte record. After immediate readback,
the host resets the CPU to its ROM via UART Ctrl-C, identifies it, reloads the
executable, and waits for the new actor to reinitialize the same card. It reads
the sector before sending any write payload in the second session. It restores
and verifies the original sector. An interruption can leave the temporary data
on disk; the backup directory printed by the harness is retained.

Use the pinned scratch setup in ../README.md, then:

    export SIMPLE_RISC=/path/to/simple-risc
    mkdir -p sd
    cp "$QOS"/hal/spectre/actors/sd/{build.sh,run.py,storage.c} sd/
    bash sd/build.sh
    python3 sd/run.py "$SIMPLE_RISC" sd/storage.bin /dev/cu.usbserial-20250303171

The FPGA and card remain powered across this reset. Neither cold boot from SD
nor sudden power-loss durability is part of this test.

Physical pass, 2026-11-15: 54 MHz RV32IMC, board ID 9819062505a27795,
QOS runtime pin 566870c3, Simple-Risc checkout 8f83a6d. Image 96144 bytes,
SHA-256 e39314dd5d34a7f131d1c0e7218661b2b3f24e26623bd5d08f1191b31c709eda.
Test record SHA-256 59733ef6b82adf448f390edaee8437f351cc5c753fe20c5d54bc4316dec9f075.
Immediate read matched, ROM identity was observed again, the fresh actor read
all 512 bytes correctly, and the original sector was restored and verified.
