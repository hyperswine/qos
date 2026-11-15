# Spectre idle-wake probe

Use the actor probe's pinned-runtime scratch build setup (../README.md).
From that same scratch directory:

    mkdir -p idle
    cp "$QOS"/hal/spectre/actors/idle/{build.sh,idle.c} idle/
    bash idle/build.sh
    python3 /path/to/simple-risc/boards/tangnano20k/run_program.py --freq-mhz 54 --protocol u --timeout 45 idle/idle.bin

Both application actors park on deadlines (10 and 18 ms). The runtime's memory
service has no outstanding request. The scheduler calls its normal machine WFI
routine through a probe-only linker wrapper. A round counts only if both sleep
markers are set, no enabled interrupt is pending before WFI, the timer is the
only enabled interrupt pending on return, and at least 1 ms elapsed across the
sample. Each actor checks its own deadline; the parent then requires the reply
to its numbered post-wake ping. This is idle wake with global interrupts masked,
not a timer trap or preemption test.

Board run 2026-11-15: RV32IMC at 54 MHz, ROM ID 9819062505a27795, pinned
runtime 566870c3. Guarded SDRAM upload, 94248 bytes, SHA-256
b8540e1b4636a88b730bbee0b39f4bd2491efdc239d17abc0b3a76e41ea9c32e.
UART transcript:

    spectre boot
    both parked; WFI -> MTIP; ping/pong OK
    both parked; WFI -> MTIP; ping/pong OK
    both parked; WFI -> MTIP; ping/pong OK
    spectre idle OK
    DONE
