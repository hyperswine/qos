# FPRLive — LiveView over a websocket, for FP-RISC apps

`programs/mods/fprlive.fpr` is the browser driver for a per-session MVU
app served from the QOS socket tier (`qosp` / virt). It is the LiveView
idea — a page split into statics and dynamics, the server owning the
model, deltas on the wire — carried over a real websocket instead of the
long-poll in `liveview.fpr`, so an update reaches the screen without the
client asking. `tests/pos.fpr` is the worked example: the point-of-sale
app from `sol/examples/pos2.sol`, one register shared by many cashiers,
each browser tab a session with its own login and cart.

```
main = FL.serve { env = e, css = G.cssFor } (FL.App init update view subs).

  init   env                 -> model               shared by every session
  update env ev model        -> (model, List MC)    ev = EMsg sid msg arg
                                                       | ETick | EGone sid
  view   sid model           -> genview tree        rendered PER SESSION
  subs   model               -> List Sub            STick ms -> server ticks
```

The four functions are `std.mvu`'s Elm surface, unchanged — the same
`App` value a game driver or the long-poll driver runs. What FPRLive
adds is the wire and the session bookkeeping.

The same idea on a PLAIN POSIX PROCESS -- `std/live` over `std/tcp`, this module's
view layer and client script unchanged -- is measured in
`../fprisc/docs/LIVE.md`; its demo is `programs/liveboard.fpr`.

## The shape: an actor per connection

The server is BEAM-shaped. An **acceptor** actor is the only thing that
touches the socket tier: it polls, hands each connection's bytes to
that connection's own actor, spawns one on first contact (spread over
the harts above 0), and closes sockets when their actors post the
connection id to a close queue. A **connection actor** owns its session
— buffer, statics, dynamics, session id — parses its own frames, sends
events to the **register**, and renders and pushes its own delta each
time the register broadcasts a new model. The register (the main actor)
is the model's single writer: one `update` per event, then the new model
to every session actor. A slow or hostile peer stalls only its own
actor; sessions scale with memory, not with a table.

Every actor takes the frame boundary from `std.mvu` each turn — state to
itself as a message, `Sys.poolReset`, state read back with `keep` — so
no loop keeps its garbage.

Measured on qosp (4 harts, this sandbox):

| sessions | per-session process memory | one checkout fanned out to all | login burst |
|---------:|---------------------------:|-------------------------------:|------------:|
| 64       | ~263 KiB                   | 63/63 deltas                   | 0.1 s       |
| 256      | ~345 KiB                   | 255/255, last after 50 ms      | 5 s         |
| 512      | ~600 KiB                   | 511/511, last after 113 ms     | 23 s        |

The 256 KiB actor stack dominates the floor; the session itself is
~10 KB. The rise per session, and the login burst time, are the app's
own shape: the POS keeps every session's cart inside the shared model,
so each broadcast copies a model that grows with the session count into
every session actor — O(n²) in sessions. Keeping per-session state in
the session actor and broadcasting a version or a diff instead of the
whole model are the next two levers; neither touches the wire.

Knobs, all build-time:

| knob | where | default | meaning |
|------|-------|---------|---------|
| `QOS_NET_MAXCONN` | `hal/unix/net_raw.h` | 1024 | connection slots (8 KiB static rx buffer each) |
| `QOS_NET_TXCAP` | `hal/unix/net_raw.h` | 256 KiB | unsent tail per peer before it is dropped |
| `QOSP_ARENA_MB` (environment, optional) | -- | unset | caps the host arena for a run; by default it is a reservation of address space with no size (`docs/BOUNDS.md`) |
| `QOSSLAB` | `fp-risc/Makefile` | 32 KiB | minimum slab for hosted apps (was 256 KiB) |
| `QOSSTACK` | `fp-risc/Makefile` | 256 KiB | per-actor stack for hosted apps |

## The wire

```
GET /            the page: generated CSS, <div id=lv-root>, the __LV__
                 seed (statics + first dynamics), the client script
GET /ws          the RFC 6455 upgrade; Sec-WebSocket-Accept = base64(
                 sha1(key ++ GUID)), both computed in FPRISC
client -> server text frames   {"msg":"buy","arg":"2"}
server -> client text frames   {"s":[..],"d":[..]}   a full render, on
                                                     connect and on a reshape
                               {"d":{"3":".."}}      a delta, computed
                                                     against what THIS session
                                                     last saw
```

Every event — any session's message, or a server tick — runs `update`
once and then pushes to *every* open session: one register, many
screens, each re-rendered through its own `view sid model` and shipped
the smallest thing that brings it up to date. A session that a change
does not touch gets an empty delta, which is elided, so an idle tab is
silent.

SHA-1, base64, the frame parser and framer, and the mask/unmask are all
in the module (`fprlive.fpr`), in FPRISC over the 63-bit tagged int:
every 32-bit intermediate is masked before each shift so nothing
overflows the tag. There is no C in the handshake.

## The client

`programs/mods/fprlivejs.fpr` is the whole client, ~150 lines, served
inline. It opens one websocket, applies `{s,d}` and `{d}` messages by
`textContent` on `<span data-slot=i>` (so a dynamic carrying user input
can never become markup), and reconnects with backoff on an unexpected
close. Client-only state — Alpine-style locals declared in the view
tree (`x-data`, `data-set`/`data-val`, `data-show`, `data-text`, and a
new `data-input` for text fields) — never round-trips unless an event
carries it as its arg. The POS uses a local for the active tab (no
server involvement to switch tabs) and a local for the login field
(sent only when the cashier presses enter or the button).

## Refusals

The server answers a misbehaving peer with the RFC's close codes and
keeps serving everyone else:

| frame                                   | close |
|-----------------------------------------|-------|
| binary, or any non-text data opcode     | 1003  |
| fragmented (FIN=0), continuation, RSV set, unmasked | 1002 |
| over 4096 bytes (incl. any 64-bit length header) | 1009 |
| a client close                          | 1000  |
| server shutdown (`MQuit`)               | 1001 (to all) |

Malformed HTTP is answered too: an upgrade without a 24-byte
`Sec-WebSocket-Key` is `400`, a request head over 8 KB is `431`, an
unknown path is `404`, and a head that arrives in pieces is reassembled
and served.

## What the adversarial harness found

`qos/tests-host/fprlive-check.py` drives the POS as several websocket
clients, well-behaved and otherwise: two-cashier flows and per-session
deltas, XSS/quote/backslash/control-byte/`\u`-escape login names, bad
numeric args (negative, huge, non-numeric, unquoted), junk and non-JSON
frames, every refused frame shape above, coalesced and byte-trickled and
16-bit-length frames, malformed and slow HTTP, the 8-connection ceiling,
a 180-event three-cashier storm with the store's invariants checked
after each burst (stock never negative, revenue equals the sum of
receipts, receipt numbers dense), a non-reading peer, and a
quit-and-restart on the same disk. Everything the run exercises is a
leg of `check-all.sh`.

Fixing what it turned up shaped the final module:

- **A frame split across TCP reads panicked the server.** The parser
  returned "incomplete" but the loop had already overwritten the
  connection's buffer with the new bytes only. Fixed by threading the
  unconsumed bytes through `pushOne` and by handling frames that arrive
  behind the HTTP upgrade in the same segment.
- **A peer that vanished without a close frame left its session alive**
  for the next peer that landed on the recycled connection id. The
  socket tier (`hal/unix/net_raw.c`) now reports EOF — a FIN, a reset,
  or a failed write — as one empty `netRead`, which both servers
  (FPRLive and the long-poll `liveview.fpr`) take as `EGone`.
- **The process heap grew ~175 KB per event.** A socket loop runs in
  one actor pool, which is reclaimed only by a reset, so every rendered
  string it ever made was retained. The loop now takes `std.mvu`'s soft
  death: each turn sends its state to itself, `Sys.poolReset`s, and
  reads the state back, so the turn's temporaries die at the boundary.
  Constant-state memory is now flat — 14 MiB steady over 10,000 events;
  growth tracks only the receipt log, which is real state.
- **Quadratic string building** in the escapers, the join helpers, and
  the frame unmask (a `strcat acc x` per byte copies the whole prefix)
  raised the per-turn high-water mark on long strings. Rewritten to copy
  plain runs whole (`substr`) and join pieces pairwise (`Core.concat`,
  `Core.joinWith`).

Moving to an actor per connection then exercised the actor runtime
harder than anything before it, and turned up five things in
`runtime/actors.c` and the host tier:

- **Eight senders per actor was a hard ceiling.** Every actor had seven
  dedicated per-sender channels plus one, and a ninth distinct sender
  panicked — a register with nine sessions could not exist. The eighth
  slot is now a shared overflow ring: many producers under a lock,
  entries tagged with the sender so selective `receiveFrom` still works
  across it. `tests/fanin.fpr` sends 40 clients through one hub and
  checks every reply is addressed.
- **A full channel panicked the sender.** A burst that outran a session's
  render died at 64 queued messages. For a while a full ring was
  backpressure (the sender yielded and retried); now capacity is a
  spawn-time choice and `send` answers with a Result (docs/MAILBOX.md):
  the register, the acceptor and every connection actor spawn Dynamic,
  so a burst grows their rings instead of stalling the sender.
- **A second enqueue of an actor already on a hart's backlog corrupted
  the list** — a waker's ship racing the receiver's own early un-block,
  then a yield. The tail could point at itself, and the selector walked
  the cycle forever with the hart reporting idle. Enqueue is now
  idempotent (a membership flag), and the walk has a cycle guard that
  names the ring. `tests/pingpong.fpr` is the cross-hart wake stress
  that reproduced it.
- **The deadlock detector was miscalibrated on hosts.** It counted idle
  passes assuming a 30 ms pacing timer; on qosp that timer is a no-op
  and a pass is a 200 µs poll, so eight quiet passes was ~1.6 ms — any
  lull with a cross-hart wake still in flight was declared a deadlock.
  It now also requires two seconds of quiet by the clock, and when it
  does fire it dumps every actor's state, wait, held messages and last
  scheduler transitions, the cross-hart rings, and each hart's phase.
- **The app image's heap range was a constant.** Raising the host arena
  to 2 GiB for more sessions put grants above the 256 MiB line the app
  was linked to treat as heap; values there were mistaken for statics
  and shared by identity — random corruption past ~220 sessions. The
  app now derives its arena end from the same `ARENA_MB`.

Two smaller ones in the socket tier: a peer that vanished mid-push (a
reset, or a failed write) was dropped silently and its slot's record
lived on for the next peer, so the tier now reports every end as an
empty read; and the blocking `netWrite` spin is gone — what the kernel
will not take is queued per connection and flushed by later pumps.

## Readiness — is this ready to host a full web app?

For a single-box app up to a few hundred concurrent sessions (a shop
till with many registers, a dashboard, an admin panel, an internal
tool), the shape is there and holds up: real websockets, an actor per
connection, per-session deltas, server push to 512 sessions in ~100 ms,
escape-safe rendering, RFC close codes, disk persistence across
restarts, sub-2 ms round trips, and flat memory under sustained load.
The handshake and framing being in FPRISC rather than C is a genuine
result, and so is what the load did for the runtime.

The limits that remain are known edges, not bugs:

- **1024 connection slots** (`QOS_NET_MAXCONN`), each with a static
  8 KiB receive buffer; the listen backlog is 128. Past that the next
  step is a dynamic table.
- **A slow reader stalls only itself**, and is dropped once 256 KiB is
  queued for it (`QOS_NET_TXCAP`).
- **No read timeout.** A peer that sends half a request head holds its
  slot and its actor until it closes.
- **The register is one actor.** Every event serializes through it, and
  every broadcast copies the model once per session. At 512 sessions a
  login burst is 23 s of that; the fix is the app's (state per session
  actor, diffs on the broadcast), not the runtime's.
- **Persistence writes a whole-state snapshot per checkout**, so the
  disk cost is quadratic in the receipt log; the harness gives it a
  64 MB disk. An append-only receipt log with a small state record is
  the right shape.
- **4 KiB frame cap, 8 KiB receive buffer, 1 KiB reads.** Fine for MVU
  events; a file upload needs fragmentation, which the parser refuses.
- **JSON `\u` escapes decode for the BMP only**; a surrogate pair
  (emoji) from a hand-written client becomes `??`. Browsers send raw
  UTF-8, so this bites only non-browser clients.
- **Header lookup is case-sensitive** (`Sec-WebSocket-Key`). Browsers
  send the canonical casing; a hand-rolled client must match.

None of these blocks the target the module was built for. They are the
list to work through before pointing it at the open internet.
