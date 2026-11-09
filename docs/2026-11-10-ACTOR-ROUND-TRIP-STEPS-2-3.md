# Actor round trip: direct handoff and inline small messages

Date: 2026-11-10. Kind: two fixes, measured, plus the sweep.

Follows [ACTOR-ROUND-TRIP.md](2026-11-09-ACTOR-ROUND-TRIP.md), which set the
bar (a null syscall, 75-98 ns on this M4) and did step 1 of its plan. This
page records steps 2 and 3. Both are on fprisc branch `qosapp-receive-loops`,
on top of `afcb0a0`: `e3b6c7d` (direct handoff) and `fa36d06` (small messages
in the ring slot). Not merged or pushed. QOS main `4e60743`, FP-RISC pin in
`fprisc.lock.json` unchanged.
Evidence: [evidence/2026-11-10-actor-round-trip-steps-2-3/](evidence/2026-11-10-actor-round-trip-steps-2-3/).

**Result: a same-hart round trip on QOS Portable is now 95-98 ns, at the
syscall bar.** Cross hart is 203-214 ns, inside the 150-200 ns floor the
first note estimated, plus about 10 ns.

## 1. Numbers

QOS Portable, `./qos.py run tests/ipcbench.fpr --harts 2`, three runs each,
back to back, warm-up run dropped:

| Case | Step 1 (`afcb0a0`) | + handoff (`e3b6c7d`) | + inline (`fa36d06`) |
|---|---:|---:|---:|
| same | 168-171 ns | 135-139 | **95-98** |
| same linear | 167-173 | 135-140 | 96-100 |
| same bounded | 188-193 | 159-163 | 161-164 |
| same 1k | 180-185 | 153-157 | 159-165 |
| cross | 325-337 | 338-386 | **203-214** |
| cross bounded | 342-354 | 352-387 | 329-349 |
| relay 16k copy (three hops) | 883-950 | 879-924 | 889-936 |
| relay 16k move (three hops) | 438-456 | 411-482 | 408-435 |

Bar: null syscall 75-98 ns, pipe ping-pong 3,125 ns (first note, section 1).

## 2. Step 2: direct handoff (`e3b6c7d`)

When an actor blocks right after waking exactly one peer on its own hart, it
switches straight to that peer instead of going back through `hart_loop`.
Conditions, all checked under `bl_lock` (runtime/actors.c `direct_handoff`):
the peer is the hart's wake hint and the only backlog entry, READY, not
running, owned by this hart; there is no run queue, no sleeper, no pending
cross-hart ring, no bound IRQ or timer, the plane is not active, and fewer
than 64 handoffs in a row (so `hart_loop` still gets a pass). The switch
clears the switched-from actor's `running` flag only once the peer is
running (`resumed()`), so a steal or a kill never sees both or neither.

About 33 ns off a same-hart round trip. Cross hart does not take the path.

## 3. Step 3: small messages in the ring slot (`fa36d06`)

A message that is one heap cell (64 bytes with its preheader, at most) of
ints, nil, actor handles and static values is copied into a cell beside its
ring slot by the sender. The receiver copies it out into its own heap. No
generic copier, no packing slab, no ARC entry.

- Applies to sends to an actor with a dedicated (unshared) channel and no
  inbox bound. Bounded inboxes (`same bounded`, `cross bounded`) keep the
  ordinary path, which is why they did not move.
- A channel's ring grows a cell area on its first inline send (a same-size
  ring swap through `ring_install`). Cells move with their slots when a ring
  grows, and when `take_at` takes from the middle of the queue.
- On for every runtime build, the native bare-metal image included (the
  arcaudit leg below runs there), except the single-hart `FPR_BUILTIN`
  build, which keeps its own message path. `FPR_INL_CELL=0` turns it off.

Same hart loses about 40 ns more. Cross hart loses ~130 ns, more than same
hart, because the ordinary path takes the global ARC lock and touches the
sender's slab from the receiver's hart: both cache lines crossed cores.
Ordinary messages that don't qualify pay +2-10 ns for the check.

`tests/base/inlinemsg.fpr` (fprisc; copy in the evidence directory) checks
order with inline and ordinary messages mixed while a ring grows, values
kept across turns, a result taken past three queued messages, and 200
actors ending with 49 unread inline messages each. It passes at 1, 2 and 4
harts. The step-2 differential run (188 programs from `tests/base` and
`tests/edge`, harts 2 and 4, against `afcb0a0`) gave the same exit codes
and output.

## 4. check-all with `fa36d06`

143 passed, 11 failed, 9 skipped, against 145/9/9 at step 1 (`3484418`).
`legs-fa36d06-qos4e60743.tsv`. Two legs changed:

- **Memory: ARC.qa audit.** Caused by step 3. `tests/arcaudit.fpr` keeps a
  received `(Int, Int)` on purpose and expects the ARC audit to count it.
  That message now rides inline, so it is the receiver's own value and ARC
  has nothing to count. This is the intended behaviour, not a leak hidden:
  the receiver's heap holds it, as it would a value the receiver built.
  Fixed in the test on this branch: the request now carries a nested pair,
  `(me, (n, 0))`, so it stays an ARC-tracked message. The leg passes with
  the edit on both `fa36d06` and `afcb0a0` (delta 0 clean, 1 leaky).
- **liveboard (std/live end to end).** A socket read timed out once. Three
  re-runs pass on `fa36d06`. Resident memory grows from run to run (1.2,
  2.8, 5.0 GiB for 100 sessions), but `afcb0a0` does the same (1.0, 3.7,
  5.0 GiB), so neither is from these steps. The growth is worth its own
  look.

The other nine failures are the known ones from step 1 (`versions`,
native instruction ratchet, dedup ratchet, Graphics.qa, install
toolchain, Sol NN, Vec fusion, Vec fixpoint, sol Ok/Err).

## 5. Left open

- **mailbox.fpr's "arc 3000" leg** no longer exercises ARC table growth,
  because its tuples now ride inline. It passes, but it tests less. It needs
  a message shape that stays on the ordinary path, as arcaudit got.
- **Bounded inboxes** don't take the inline path (the bound is charged per
  message on the ordinary path). `same bounded` stays at ~160 ns.
- **Cross hart** is at ~205 ns: about 2x the bar. What remains is the two
  cache-line transfers each way and the wake.
- **Not measured:** the native kernel (RISC-V, QEMU) and the Pi 4B.
- When QOS pins this fprisc, the arcaudit edit has to land with the pin.
