# Spectre UART RX actor probe

Start in the pinned scratch build from ../README.md:

    mkdir -p uart
    cp "$QOS"/hal/spectre/actors/uart/{run.py,uart.c} uart/
    sol "$QOS"/hal/spectre/actors/build.sol . uart
    python3 uart/run.py "$SIMPLE_RISC" uart/uart.bin /dev/cu.usbserial-20250303171

The host uses the existing Simple-Risc ROM library for guarded SDRAM upload.
It waits for each READY marker, delays 80 ms to let the receiver block, and
sends one byte. The second injection therefore cannot be part of the first
FIFO drain. The actor installs itself as the scheduler IRQ router; hardware
wakes WFI with MEIP, the scheduler claims PLIC source 10 and delivers the
source number to its mailbox. Only then does the actor read RXDATA and forward
the byte to the waiting parent. The probe requires a fresh external-pending
transition across WFI for each input.

The board's RX interrupt is level-sensitive. Keep the source claimed and
masked until RXDATA has been read, then complete and re-enable it. Completing
at claim time could latch a new pending request against the same unread byte.
This probe enables only RX interrupts. After checking 0x41 and 0x5a the parent
sleeps for 10 ms, exchanges a fresh message/reply with the receiver and checks
for exactly two claims and acknowledgements. This exercises synchronous IRQ
delivery from the native scheduler, not an asynchronous machine trap handler.

Physical run 2026-11-15: RV32IMC 54 MHz, ROM 9819062505a27795, 94968-byte
image SHA-256 13833ceb83483a67ebf3267bf21e3956aa03d3be3d09dab56af320e8e6dfa692.
Observed output (READY is printed by the receiver, received by the parent):

    spectre boot
    READY A
    READY B
    received 41
    received 5a
    2 claims/acks; scheduler ping/pong OK
    DONE
