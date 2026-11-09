# Portable message-passing targets

Date: 2026-11-09. Kind: proposal. QOS Portable, with hosted figures only as a
same-machine reference.

The target is useful operations, not just a fast pingpong. A two-message held
service operation must beat a matched cheap syscall on the target machine.
Open/write/close per operation must not be the high-volume path. Hundreds of
nanoseconds are a provisional raw IPC baseline, not proof that QOS is faster
than the kernel.

This note records the sourced historical benchmarks and an order of work to
get held operations into that range. It does not report new measurements.
Sources are Apple silicon / arm64 macOS runs in the documents below, at QOS
`5feea4b`. They are not native-kernel, Pi, Linux, or current fprisc
performance claims.

The 6 November baseline used QOS `f2c3a63` and sibling fprisc `aee02d8`, not
the release pin. The 7 November landed-spin record reports smoke tests with
sibling fprisc `8af12a2`. Preserve these build identities rather than
presenting all rows as one current-tip benchmark. Runs were limited and some
rows varied by up to 12%.

Related: the [amended zero-overhead OS proposal](2026-11-06-ZERO-OVERHEAD-OS-AMENDED.md),
the [review note](2026-11-07-ZERO-OVERHEAD-OS-REVIEW-NOTE.md), and the
[landed Portable block-spin record](2026-11-07-PORTABLE-BLOCK-SPIN.md).

## Raw IPC

A round trip is a request plus reply, not one send. Source B:
`tests/ipcbench.fpr`, two harts with `spawnOn` placement. The 2 µs value is
the maximum mailbox recheck window on an otherwise idle hart, not a delay
added to every message.

| Portable round trip | Spin 0 | Spin 2 µs |
|---|---:|---:|
| Same hart | 297 ns | 279 ns |
| Same hart, bounded inbox | 310 ns | 297 ns |
| Cross hart | 5,209 ns | 394 ns |
| Cross hart, bounded inbox | 5,321 ns | 458 ns |
| Same hart, 1 KiB request | 316 ns | 290 ns |

| Earlier reference (source A) | Measured RTT |
|---|---:|
| Hosted, same hart | 180 ns |
| Portable, same hart | 292 ns |
| Hosted, cross hart | 347 ns |
| Portable, cross hart, before hook | 4,380 ns |
| Portable, cross hart, temporary hook | 446 ns |
| C two-thread atomic pingpong | 106–127 ns |
| C parked condvar pingpong, quiet | 4.4–6 µs |

The earlier same-hart Portable–hosted gap is about 110 ns and remains
unexplained. The atomic reference crosses cores; it is not a lower bound for
same-hart actor switching. Do not infer that hosted same-hart has only tens
of nanoseconds left to remove. Parked results are macOS/load-sensitive and
reached 12.6 µs under load.

## Service and payload costs

These are different benchmark paths, not an additive breakdown of the held
write. Source A, historical one-hart comparison, unless noted.

| Path | 1 hart | 2 harts |
|---|---:|---:|
| Open/write/close · 8 messages | 2,251 ns | 3,608 ns |
| Held write · 2 messages | 553 ns | 706 ns |

Held handles demonstrate a 4.1× improvement in the one-hart endpoint
benchmark without a runtime descriptor table. The held-minus-raw difference
of about 260 ns does not isolate correlation overhead: owner work, envelopes
and control flow differ. Source B repeats found open/write/close at
2,025–3,612 ns and held writes at 525–781 ns; actor placement prevents
attributing that spread to spin.

| Payload / other path | Historical result |
|---|---|
| Hosted, 1 KiB request · source A | 198 vs 180 ns RTT |
| Portable, 16 KiB copy / move · source A | 1,288 / 766 ns |
| Portable, 16 KiB copy / move · source B, spin on | 1,195 / 711 ns |
| Uncontended inbox bound · source A | 15–20 ns per send |
| Native `qos_store_call`, after empty poll | Sleep up to 100 µs |

16 KiB rows are whole three-hop relay cycles, not per-hop costs. Small
copying adds about 18–20 ns hosted and is inside run-to-run noise on
Portable. The storage sleep is conditional and capped by the remaining
deadline: it is neither an unconditional operation floor nor the raw IPC
floor. Its frequency is unmeasured.

## What acceptable means

| Use case | Proposed acceptance |
|---|---|
| Raw same-hart IPC | 279 ns Portable / 180 ns hosted are reference levels to improve, not final syscall-replacement targets. |
| Raw cross-hart IPC | Retain the documented within-2× same-hart gate, with tails, CPU and contention qualified. 394 ns is an interim result, not an inner-loop guarantee. |
| High-volume held service call | Two steady-state protocol messages; move toward the historical 180–280 ns raw reference band, then lower the raw floor. This is a directional goal, not an achieved or validated hard limit. |
| Syscall replacement | Beat a matched cheap syscall for comparable useful work, on the same hardware/OS, at the intended load and concurrency. |
| Open/write/close | Keep for convenience or cold operations, not sustained hot loops. |
| Native storage wait | Remove sleep-after-empty polling latency; wake for reply, death, cancellation or deadline without monopolising the hart. |

No matched syscall benchmark exists in this evidence, so a universal numeric
syscall threshold would be invented. Measure the actual kernel alternative
before setting hard latency and throughput budgets. Report useful operations
per second as well as round-trip latency; serial pingpong alone cannot
establish system throughput or scalability.

## Implementation order

1. Confirm the shipped Portable image contains the landed block spin.
   Verify `hal_block_spin_ns()` returns the default 2,000 ns; the comparison
   build uses `QOSCFLAGS_EXTRA=-DQOS_BLOCK_SPIN_NS=0`. Rebuild the image
   rather than assuming a new checkout changed an old binary. Repeat
   pinned-placement same/cross-hart tests. Keep native kernel spin at zero
   pending board measurements; 2 µs is not a proven optimum.

2. Count hot `Svc` calls and adopt existing held handles immediately.
   Rank the 58 tracked `.fpr` call sites by execution frequency and messages
   per useful operation. Use `EP.open`, repeated operations and explicit
   `EP.close` in hot loops: eight messages become two. Measure application
   workloads, not just `epbench`. Preserve rights, expiry, owner replacement,
   revocation and bounded cleanup; longer handle lifetime is an explicit
   semantic choice. Do not introduce a descriptor table first.

3. Measure and replace the storage poll/sleep path, in parallel with
   held-handle work. Count first-poll hits, empty polls, sleeps and wait
   durations; record native key-value latency distributions. Implement the
   already-proposed deadline-aware blocking C receive. Preserve
   correlation/source filtering, unrelated and late messages, the 10 s
   deadline, invalid-reply handling and write-side outcome-unknown refusal
   behavior.

4. Profile the fixed path before choosing the next refactoring. Use
   identical placement and owner work. Add id generation, correlation
   envelopes, wrappers and matching one at a time; count copies, slabs, ARC,
   queue activity, allocations and switches. Explain the Portable-versus-hosted
   and held-versus-raw gaps with matched evidence. Direct/indirect call
   microtests were both 0.8–0.9 ns; dispatch alone does not explain 110 ns.
   Cross-image lost inlining remains a hypothesis, not a measured
   attribution. Promote one measured optimization at a time, preserving
   refusal, accounting, ordering and scheduling contracts. Do not remove
   bounds or ownership checks merely to hit a latency goal.

5. Then qualify the documented secondary mechanisms. Signal the Portable
   doorbell only for waiting workers, with an atomic latch/parked handshake
   and lost-wake tests. Keep the latch and 20 ms cap; the cap must not hide
   a lost wake. Consider endpoint slot storage only after profiling; retain
   per-access identity, generation, expiry and liveness checks. Prioritize
   ownership transfer for large payloads, not tiny messages. `sendLinear`
   moves only a received message root; locally built values still copy, and
   the native shared plane currently refuses moves. Outgoing-slab placement
   and shared-plane transfer need separate compiler/runtime design and
   ownership gates.

Defer credits/certificates, descriptor tables, direct handoff and
scheduler-policy changes until measured residual costs justify them.
Register fuel is a separate coordinated ABI project; it is not evidence that
the message path will get faster.

## Measurement and promotion gates

1. Record hardware, OS, affinity, hart count, power conditions, exact
   QOS/compiler/runtime identities, flags and instrumentation. Keep
   release-pin and sibling builds separate.
2. Warm up and interleave repeated baseline/variant runs. Publish run
   counts, median, variability, p95/p99, useful throughput, CPU and memory.
   Separate startup from steady state and measure counter overhead off/on.
3. Test same/cross-hart, sparse and saturated traffic, contention,
   oversubscription, unrelated runnable actors and 60 s idle. Qualify tails
   and fairness rather than accepting a good mean alone.
4. For held handles, count two hot-operation messages separately from
   open/close, expiry, invalidation and cleanup. Gate wrong identity, owner
   restart, death, stale handles, close races and acknowledged revocation.
5. For blocking receive and doorbells, exercise replies/rings before, during
   and after waiter registration, cancellation, death, stale/duplicate
   replies and deadline races. Define the winning event at the deadline and
   verify other actors progress while a wait is parked.
6. Before promotion, set numeric regression tolerances from measured
   baseline noise and agree a matched syscall budget. Preserve historical
   records; publish each new run as new evidence rather than overwriting old
   numbers.

First deliverable: one repeatable evidence record covering raw IPC, held
versus open/close service calls, a matched syscall reference and storage
poll/sleep counters. Ship held-handle adoption and blocking receive as
independently measured changes; use the resulting profiles to choose the
next runtime refactoring.

## Sources

- A. [Amended zero-overhead OS proposal](2026-11-06-ZERO-OVERHEAD-OS-AMENDED.md)
  and [historical IPC and endpoint raw output](evidence/2026-11-06-ipc-costs.txt);
  [C IPC floor raw output](evidence/2026-11-06-ipc-floor.txt).
- B. [Landed Portable block-spin record](2026-11-07-PORTABLE-BLOCK-SPIN.md)
  and [landed-spin raw output](evidence/2026-11-07-portable-block-spin.txt).
- [Review note](2026-11-07-ZERO-OVERHEAD-OS-REVIEW-NOTE.md).

Sources A and B were read for this proposal. Raw evidence links are their
cited supporting records; no new measurement or implementation is claimed
here.
