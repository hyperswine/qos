# Portable: the actor block spin

Date: 2026-11-07. Kind: change record. QOS Portable only.

The first item of the [amended zero-overhead OS proposal](2026-11-06-ZERO-OVERHEAD-OS-AMENDED.md).
One definition in `qos/appside/hal.c`:

```c
#ifndef QOS_BLOCK_SPIN_NS
#define QOS_BLOCK_SPIN_NS 2000
#endif
uw hal_block_spin_ns(void) { return QOS_BLOCK_SPIN_NS; }
```

## What it does

An actor about to block on an otherwise idle hart re-checks its mailbox for
up to `hal_block_spin_ns()` before it blocks (`spin_until` in
`fprisc/runtime/actors.c`, guarded by `hart_quiet`: the hart's run queue,
backlog and incoming ships must all be empty, and the spin ends as soon as
any of them is not). The posix machine has defined this hook at 2 µs since
1 October ([XHART](../../fprisc/docs/2026-10-01-XHART.md)). QOS never
defined it, so the runtime's weak default of 0 applied in every Portable
image, and a cross-hart reply paid a block, a wake, a ship and a kernel
sleep.

A freestanding image has no environment, so the value is a build constant.
`QOSCFLAGS_EXTRA=-DQOS_BLOCK_SPIN_NS=0` builds the comparison arm, which is
the behaviour before this change. The native kernel does not link
`appside/hal.c` and keeps the weak 0, as the proposal asked.

## Measured

`tests/ipcbench.fpr`, two harts, placement pinned by `spawnOn`
([raw output](evidence/2026-11-07-portable-block-spin.txt)):

| ns per round trip | spin 2 µs | spin 0 |
| --- | ---: | ---: |
| Same hart | 279 | 297 |
| Same hart, bounded inbox | 297 | 310 |
| Same hart, 1 KiB request | 290 | 316 |
| Cross hart | **394** | 5,209 |
| Cross hart, bounded inbox | 458 | 5,321 |
| Relay of 16 KiB, copy / move (three hops) | 1,195 / 711 | 1,261 / 746 |

Cross hart is 1.4x same hart, inside the proposal's 2x acceptance. Same-hart
rows are within run-to-run noise of each other.

Idle CPU, default hart count (10), one run per arm: a program that sleeps
30 s cost 6.31 s of child CPU with the spin and 6.68 s without, against
6.35 s and 6.29 s for a program that prints and exits. The idle 30 s cost
under 0.4 s in either arm, which is inside the noise of the compile and
link that `qos.py run` does each time.

`tests/epbench.fpr` is not a clean test of this change because
`AC.spawnWith` chooses the hart: at two harts its open-write-close ranged
2,025 to 3,612 ns across three runs with the spin and 2,041 to 2,071
without, and the pre-hook run of 6 November gave 3,608 with the spin
absent. The held-handle write was 525 to 781 ns in every arm. The spread
follows where the namespace and owner land, not the spin.

`./qos.py test` with the hook in place: smoke 16/16 in 107 s (sibling fprisc
`8af12a2`, not the release pin).

## Not done

- The conditional doorbell (ring only a worker that is in the wait) is a
  separate patch with its own memory-ordering gate.
- No Pi 4B measurement. The proposal's open question 1 (which value passes
  the CPU and latency gates on four loaded cores) stays open; 2 µs is the
  posix machine's value, not a measured optimum.
- No contended or oversubscribed run. `hart_quiet` is the only guard.
- An adaptive window remains an idea.
