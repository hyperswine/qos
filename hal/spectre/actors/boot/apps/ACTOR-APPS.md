# Spectre application actors

The shell supervises two trusted applications on one hart. `run NAME` reads
the executable by QLog name and prints its job slot, 1 or 2.
`status 1` reports that slot's scheduler yield count, exit code, or stopped
state. `stop 1` kills its current actor. Bare `status` and `stop` address the
most recently launched slot. Slot numbers are reused on subsequent launches.
Each slot has a 4 KiB image window and callbacks bound to that window. A third
simultaneous launch reports busy. The shell yields while waiting for UART input.

SXA2 retains the console callback and adds a poll callback as entry argument
a1. The sample build tool inserts a poll at typed RV32 basic block entries,
including the target of the spin program's tail-recursive loop. The trampoline
preserves the integer caller-saved registers and the host yields every 128
polls. This is cooperative scheduling. The probe does not establish bounded
stop latency for arbitrary uninstrumented native instructions, blocking HAL
calls or corrupted code. There is no privilege separation or fault containment.
SXA1 has no poll callback; only the earlier known terminating hello demo is
accepted by length and CRC as a compatibility convenience, not authentication.

Compile spin.fpr and pendulum.fpr separately with build-app.py, using the
compiler argument shown in README.md. From this directory run
`SIMPLE_RISC=/path/to/simple-risc python3 check-two.py` on a freshly booted
board with the earlier hello app and notes/spectre.txt present. The harness
installs and verifies both loop images by name, checks independent progress,
stops one, and reuses its slot for hello while the other continues.

## Integer messages between apps

Build ping.fpr and pong.fpr separately with the extra build-app.py argument
`--mailbox` to select SXA3. The first two entry registers retain the SXA2
console and poll callbacks. Registers a2 and a3 supply peerSend and mailReceive.

`peerSend value` sends a tagged Int to the actor currently occupying the other
slot. It returns 1 on mailbox admission and 0 if the peer is absent or the
runtime refuses delivery. `mailReceive 0` blocks the calling actor in QOS
receive until its next message. Peer identity is resolved at each send, so an
application that needs a stable peer across slot reuse needs a stronger API.

Run apps/pong.sxa first. It waits, echoes the integer it receives, and returns
that integer. Then run apps/ping.sxa. It sends 37 and returns the value of its
blocking receive. Both slots should show exit 37. The UART harness exercises
this twice with `python3 check-two.py --mailbox`, including a named filesystem
read while the responder is waiting.
