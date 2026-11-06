# Toward a zero-overhead QOS, amended: measured costs and a revised order

Date: 2026-11-06. Kind: amended proposal with measurements. No runtime change
is implemented by this page. It adds two benchmark programs.

Baseline: QOS `f2c3a63`, sibling FP-RISC checkout `aee02d8` (codegen 204).
`fprisc.lock.json` still names `1a09f01`, so these are not the release pin's
results. Host: arm64 macOS on Apple silicon, QOS Portable (`qosp`).

This page amends [the zero-overhead OS assessment](2026-11-06-ZERO-OVERHEAD-OS.md)
written earlier today. That page ranked twelve moves from source inspection.
This one measures the message path on QOS Portable, checks the cost table
against the code, and re-ranks. The original's thesis (decide once, then pay
only for the work), its section 1 (what already qualifies), section 4
(transactions) and section 6 (what not to do) stand unchanged and are not
repeated.

## Summary

**What the measurements say** (`tests/ipcbench.fpr`, `tests/epbench.fpr`; raw
output in [evidence](evidence/2026-11-06-ipc-costs.txt)):

- A cross-hart round trip on QOS Portable costs **4,380 ns**, against 347 ns on
  the hosted FP-RISC runtime. With a two-line hook added to the app-side HAL
  as an experiment, it costs **446 ns**.
- A same-hart round trip costs 292 ns on Portable and 180 ns hosted. The 110 ns
  difference is not explained yet.
- A write that opens and closes its endpoint each time, as `Svc.write` does,
  costs **2,251 ns**. The same write on a held handle costs 553 ns.
- Copying is cheap for small messages and dominant for large ones: 1 KiB adds
  about 20 ns to a hosted round trip (on Portable it is inside run-to-run
  noise), while moving instead of copying a 16 KiB relay saves 520 ns per hop.
- An inbox bound costs about 15 ns per send when uncontended.

**What changes from the original:**

1. Move 1 keeps its rank and changes mechanism. The gain comes from the
   actor-level block spin, which QOS does not provide, and not from a spin in
   `park.c`.
2. Move 2 as written would not remove the copies it targets. It merges with
   Move 7 into one later item.
3. Move 5's proof machinery is deferred. The cost it removes is small, and a
   cheaper fix exists.
4. Move 9 rises: the native storage trampoline has a floor of about 100 µs per
   operation.
5. Move 3 is confirmed at 4.1x per operation, with its call-site count
   corrected from about 700 to 58.

**Revised order:** block-spin hook, blocking C receive, descriptor table,
lease sweep, then the rest. The table is in "The moves, re-ranked" below.

## Measurements

### One message

Nanoseconds per round trip (a request and its reply), clock read around each
loop. `ipcbench.fpr` imports nothing, so the same file runs on both runtimes.

| Case | Hosted FP-RISC | QOS Portable | Portable + block-spin hook |
| --- | ---: | ---: | ---: |
| Same hart | 180 | 292 | 292 |
| Same hart, `sendLinear` of a built value | 180 | 279 | 282 |
| Same hart, bounded inbox | 201 | 305 | 309 |
| Same hart, 1 KiB request | 198 | 299 | 309 |
| Cross hart | 347 | 4,380 | 446 |
| Cross hart, bounded inbox | 352 | 4,468 | 518 |
| Relay of 16 KiB, copy (three hops) | 878 | 1,288 | 1,292 |
| Relay of 16 KiB, move (three hops) | 441 | 766 | 779 |

The hook is `uw hal_block_spin_ns(void) { return 2000; }` appended to
`qos/appside/hal.c`, run once and reverted. It is an experiment, not a patch.

On the hosted runtime the two spin windows separate cleanly (an earlier
program of the same shape, 1,000,000 round trips):

| Hosted, cross hart | ns per round trip |
| --- | ---: |
| Default (both spins on) | 368 |
| Hart-park spin off (`FPR_SPIN_US=0`) | 365 |
| Both off (`FPR_BLOCK_SPIN_NS=0` as well) | 4,398 |

### One endpoint operation

`epbench.fpr` reaches an owner that answers at once, through the real
namespace and the real `EP` client calls.

| QOS Portable | 1 hart | 2 harts |
| --- | ---: | ---: |
| Open, write, close per write (8 messages) | 2,251 ns | 3,608 ns |
| Write on a held handle (2 messages) | 553 ns | 706 ns |

A held write is one correlated `AC.call`. It costs 553 ns where a raw round
trip costs 292 ns, so the call layer adds about 260 ns.

## Corrections to the original's cost table

| Item | Original claim | Finding |
| --- | --- | --- |
| C1 | Every `send` deep-copies | Correct. For small messages the copy is not the main cost: about 90 to 150 ns of each message is fixed path. |
| C2 | `sendLinear` is an unused fast path, about 220 sites against thousands of `send`s | It has one `.fpr` call site in QOS and none in FP-RISC `std`, against about 740 and 80 occurrences of `send`. It moves only a **received message root**. A locally built value is copied and then consumed (180 against 180). Under the shared memory plane that native apps use, `fpr_arc_movable_root` returns 0, so it never moves there. |
| C3 | A declared inbox bound costs two locks and a charge walk per send | Correct. Measured at about 15 to 20 ns per send uncontended on one hart. |
| C4 | Portable's doorbell is a mutex and a signal per message, with no spin window | Correct as read, but the missing piece that matters is elsewhere: QOS defines no `hal_block_spin_ns`, so the runtime's weak default of 0 applies and an actor about to block never looks again first. |
| C5 | `Svc.read`/`Svc.write` open per operation, about 700 call sites, 8 messages | 8 messages is correct (open 4, operation 2, close 2). The call sites number 58 in tracked `.fpr` files. |
| C6 | The endpoint owner filters all leases on every request | Correct for the deadline-aware owner (`simpleUntil`). The plain owner loop does not. |
| C7 | Admission is O(backlog) under a lock | Correct. `refill` calls it up to `RQ_CAP` times, so one refill is O(`RQ_CAP` x backlog). |
| C8, C9, C11, C12 | Spawn reservations, charge array, launch re-hash, list walks on open | Confirmed at the cited lines. Not measured. |
| C10 | The native storage trampoline polls with no blocking receive, burning a hart for up to 10 s | It does not burn a hart. It polls once, finds nothing because the request was only just sent, and sleeps 100 µs before each further poll (`loader/process.c`, `fpr_actor_sleep_us`). The cost is a latency floor of about 100 µs on every native storage operation. |

Two costs the original does not list:

- **Portable's same-hart path is 1.6x the hosted one** (292 against 180 ns).
  Every app-side send and receive goes through the plane's function table
  (`fpr_plane_actors->send_as`), which is one candidate. It is not profiled.
- **A correlated call costs about 260 ns more than the two messages it
  sends** (553 against 292 ns). The id, the envelope, the `IoV` wrapper and
  the reply match are the candidates. Also not profiled.

## The moves, re-ranked

| Rank | Move | Evidence | Effort | Against the original |
| --- | --- | --- | --- | --- |
| 0 | Benchmarks and message counters in the tree | Two programs added here; counters still to add | S | Was section 5; now first |
| 1 | Block-spin hook in the app-side HAL; ring only a waiting worker | 4,380 to 446 ns cross hart, measured | S | Move 1, new mechanism |
| 2 | Blocking C receive for the native storage trampoline | About 100 µs floor per operation, read from source | S | Was Move 9 |
| 3 | Per-process descriptor table | 2,251 to 553 ns per operation, measured | M | Move 3, unchanged design |
| 4 | Endpoint-owner slot array and lazy sweep | Not measured | S | Move 4, unchanged |
| 5 | Profile the two unexplained fixed costs | 110 ns per round trip, 260 ns per call | S | New |
| 6 | Build a message in its own slab and hand the slab over | Move halves a 16 KiB relay; no gain from `sendLinear` on built values | L | Merges Moves 2 and 7 |
| 7 | Sender credits for bounded inboxes | About 15 ns per send | M | Replaces Move 5's first step |
| 8 | O(1) admission | Not measured | M | Was Move 6 |
| 9 | Lazy reservations, verify at install, transactions, direct handoff | Not measured | S to L | Moves 8, 10, 11, 12, unchanged |

### Move 1: the block spin, then the doorbell

On the hosted runtime an actor about to block on an otherwise idle hart
re-checks its mailbox for up to `hal_block_spin_ns()` first
(`spin_until`, `fprisc/runtime/actors.c`). The posix machine sets 2 µs. QOS
sets nothing, so the spin is off, and every cross-hart reply pays a block, a
wake, a ship and a sleep in the kernel.

- Define `hal_block_spin_ns` for Portable. The runtime already guards the
  spin with `hart_quiet`, so no actor waits behind it.
- Then make `qosp_hart_ring` signal only when the worker is in the wait, as
  `machine/unix/park.c` does with its `waiting` word. On the hosted runtime
  the park-level spin added nothing once the block spin was on, so the
  spin-in-`park.c` half of the original Move 1 is dropped.
- Keep the latch and the 20 ms cap.
- Leave the native kernel at 0 unless a measurement on the board says
  otherwise. The runtime's own comment gives the reason: `wfi` and an IPI are
  cheap on real harts.

Acceptance: `ipcbench` cross-hart within 2x of same-hart on Portable; idle
CPU per hart over 60 s unchanged; the Pi 4B run recorded separately, since
four cores under load are where a spin can cost.

### Move 2: a blocking C receive

Add a blocking `fpr_receive_from_c` that parks the calling ACB until the
storage actor answers or the deadline passes, and use it in `qos_store_call`.
The reply contract and the 10 s deadline are unchanged.

Acceptance: a native app's key-value round trip measured before and after,
with the floor gone; the deadline and dead-actor refusals keep their text.

### Move 3: the descriptor table

As the original describes it. The measurement gives it a number: an
operation on a held handle costs a quarter of an open-operate-close. The
correctness argument (an fd the runtime issued, in place of a lease key the
client claims) also stands.

What changes is the order of work. With 58 call sites, the first step is the
message counter, to find which of them are hot. A site that runs once per
launch does not need the table.

### Move 6: one slab per message

This replaces "make move the default" and "construction in place".

`sendLinear` cannot make a built value cheaper, because the value lives in
the sender's pool and has to leave it. What removes the copy is building the
value in a slab of its own when the compiler sees it die at the send, and
transferring that slab. This is the sender-owned form the original's open
question 4 asks about, and it reuses what the transfer path already does for
a received root.

- It needs a compiler change (place the allocation), a runtime change (a
  fresh ownerless slab per outgoing message) and, for native apps, a
  transfer path under the shared memory plane.
- Its gain scales with size. At 1 KiB it is about 20 ns hosted and inside
  run-to-run noise on Portable; at 16 KiB it is about 520 ns per hop.
- So it ranks below the fixed-path items, and its first users should be the
  large payloads: file contents, frames, listings.

### Move 7: credits in place of per-send charging

The bound is enforced today by a lock and a count on the receiver at every
send. The same guarantee holds if the receiver grants each sender a number of
credits when the channel is bound, and the sender counts down locally. A
send then touches no shared word until the credits run out.

The original's proved queue depth would remove even that, but the compiler
does not compute a queue depth for general actor programs, and the cost at
stake is about 15 ns. Keep the certificate idea for the static-arena work,
where the proof already exists for controlled sequences.

## Gates

The original's section 5 stands, with two programs now in the tree:

| Program | Command | Reports |
| --- | --- | --- |
| `tests/ipcbench.fpr` | `./qos.py run tests/ipcbench.fpr --harts 2` | ns per round trip: same hart, cross hart, bounded, 1 KiB, relay copy and move |
| `tests/epbench.fpr` | `./qos.py run tests/epbench.fpr --harts 1` | ns per write: open-write-close against a held handle |

Both carry an `#: expect` line and take about ten seconds. Still to add from
the original's list: the debug-profile message counter, `spawn`, `launch`,
`frame` and `idle`.

## Cross-layer notes

- The language-level order the original points to is complete. Its successor
  is [the fixed-costs proposal](../../fprisc/docs/2026-11-06-FIXED-COSTS-PROPOSAL.md)
  in FP-RISC.
- That proposal's step 4 keeps the fuel counter in x27 on AArch64. QOS apps
  share that register convention, so it is a QOS ABI decision as well.
- The pin trial to `e138e65` was recorded as a go today while the lock still
  names `1a09f01`. Re-run both programs once the pin moves.

## Open questions

1. What value should Portable's block spin take: the posix machine's 2 µs, or
   a figure measured on the Pi 4B?
2. Does the descriptor table belong to the runtime or to `std/actor`? (Carried
   from the original, unanswered.)
3. Is a static-scheduler profile worth having for the fully declared case?
   (Carried, unanswered.)
4. Should the 260 ns call overhead be looked at before the descriptor table?
   If most of it is avoidable, every endpoint operation gains, cached or not.

## Limits of this evidence

- One machine, arm64 macOS, QOS Portable only. Nothing here is measured on the
  native kernel, under QEMU or on the Pi.
- Each configuration ran once or twice. Two Portable runs of the same program
  differed by up to 12% on single rows (335 against 299 ns for the 1 KiB
  case).
- The compiler is the sibling checkout, not the release pin.
- The block-spin figure comes from a temporary two-line edit, reverted after
  one run. Idle CPU with the spin on was not measured.
- Moves 2, 4, 8 and 9 rest on reading the source, not on a measurement.
- The hosted spin table comes from an earlier program timed as a whole
  process, not from `ipcbench`.
