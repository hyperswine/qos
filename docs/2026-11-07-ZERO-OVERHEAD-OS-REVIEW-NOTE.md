# Zero-overhead OS: corrections to the second-review addendum

Date: 2026-11-07. Kind: review note. No runtime change, no new measurement.

Scope: commit `b7425d5` ("second review addendum, IPC floor measured"),
which edited [the original assessment](2026-11-06-ZERO-OVERHEAD-OS.md) and
[the amended proposal](2026-11-06-ZERO-OVERHEAD-OS-AMENDED.md) and added
`tests/ipcfloor.c`. This note records what in that addendum holds, what
does not, and what it changed about the record. It amends nothing in place.

## What holds

- **The IPC floor reference** (`tests/ipcfloor.c`). A two-thread atomic
  ping-pong gives the cross-core round-trip floor, 106 to 127 ns on this
  machine class, and the parked-condvar mode (4.4 to 6 µs) brackets where
  Portable's default cross-hart figure of 4,380 ns sits. That is the right
  evidence that Portable pays a blocking wake per message.
- **The plane dispatch is exonerated.** A predicted indirect call costs the
  same as a direct one, so the 110 ns same-hart gap between Portable and the
  hosted runtime is not `fpr_plane_actors`. Profiling the wrapper layers
  next (id, envelope, copy, reply match) is the right probe.
- **Held handles before a descriptor table.** Application-level, no runtime
  change, measured at 4.1x in `epbench`.
- **The outgoing-slab item reuses an existing analysis**, and its rewritten
  text correctly asks for whole-graph ownership rather than root liveness.

## What does not hold

1. **"Hosted same-hart is about 1.5x the floor; only tens of nanoseconds of
   headroom remain."** The spin floor is a cache-line round trip between two
   cores. A same-hart actor round trip has no cross-core traffic: it is two
   sends, two receives and two user-level context switches on one thread.
   Its floor is a coroutine switch pair, tens of nanoseconds, not 106. The
   180 ns is almost entirely software; the receive-turn work of 19 October
   took one turn from 214 to 123 ns, which is what remaining headroom looks
   like. The valid floor comparison is cross-hart: 347 ns against about
   115, roughly 3x.
2. **C1 softened into a non-claim.** "These runs do not isolate the fixed
   path" is not right: a 1 KiB payload adds 18 ns to a 180 ns round trip,
   so about 90 ns of each message is fixed path, by subtraction. It is a
   measurement.
3. **C10: "a reply can already be ready at the first poll."** True in
   principle, not in practice: the poll runs immediately after the send,
   before the storage actor has been scheduled. The practical effect remains
   a penalty of up to 100 µs on nearly every native storage operation. The
   poll and sleep counter the addendum asks for will settle it; until then
   the item keeps its rank.

## What it changed about the record

- **The original page was rewritten in place** (226 lines changed): its
  ranked moves became "contracts", and its figures of about 700 `Svc` call
  sites and about 220 `sendLinear` sites are gone. The docs rule is
  chronological and never reconciled; the corrections now exist only in the
  amended page and in this note. The original's text as assessed is at
  `c3d19f1` and before.
- **Chunked fuel was moved to "deferred until an execution-boundary proof
  passes"** without evidence. The FP-RISC fixed-costs proposal charges
  `min(iterations left, fuel left)` per chunk, which keeps every preemption
  tick identical by construction; its gate is an exact tick trace. It is a
  measured 20% on byte loops and stays in that proposal's step 4.
- **The gates grew faster than the code.** The two pages now run to about
  820 lines and the first item is still a two-line hook that reuses
  `spin_until`, code that already runs on every posix host. The hook needs
  a configurable value with zero as the comparison arm, `ipcbench`, and a
  60 s idle-CPU check. The lost-wake and memory-ordering gates belong to the
  conditional-doorbell patch, where ordering is the risk.

## Order from here

1. Land the block-spin hook behind a configurable value, zero kept as the
   comparison; record `ipcbench` and idle CPU.
2. Add the poll and sleep counter to `qos_store_call`, then the blocking
   receive.
3. Adopt held handles at the hot `Svc` sites once the message counter says
   which they are.
4. Keep the adaptive spin window for after the first fixed-window number
   exists.
