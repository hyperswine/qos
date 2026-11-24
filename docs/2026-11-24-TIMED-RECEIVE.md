# Deadline receives for QOS (2026-11-24)

The 2026-11-24 overhead review measured std/actor's deadline call at
**154 us per call** on an idle machine where a blocking `receiveFrom`
answers in under 1 us (same hart) or ~2 us (cross hart): `awaitReplyUntil`
polls `receiveFromNow` and naps 100 us between looks, so every deadline
call pays at least one nap. QOS also had several "look, then sleep a fixed
period" loops: the hosted timer's 10 ms sleeper slices, the lifecycle
loop's 25 ms nap, the system endpoint's 20 ms idle nap, the app session's
startup poll and every app's 16 ms idle nap.

FP-RISC main grows builtin deadline receives (`receiveUntil`,
`receiveFromUntil`, plane ABI v7; hyperswine/fprisc#112). QOS's pinned
runtime (`fprisc.lock.json`) predates them, so this change adds the same
waits as QOS primitives on what that runtime already exports
(`fpr_wait_{any,from}_until_c`: park on the mailbox and the hart's sleeper
list through the block/recheck handshake, so a send from any hart or the
deadline wakes the actor, whichever comes first).

## Primitives (`hal/timed_receive.c`, declared in `core/foreign.fpr`)

| primitive | answers |
| --- | --- |
| `Sys.receiveUntil me until` | `Ok message` (any sender) or `Err "deadline"` |
| `Sys.receiveFromUntil me from until` | `Ok message` from `from` (others stay queued), `Err "deadline"`, or `receiveFromNow`'s dead-sender `Err` |
| `Sys.waitInbox me until` | takes nothing: `1` a message is already queued, `2` woken after parking, `0` no timed wait here |

`until` is a std/actor deadline (absolute ms on `Sys.uptimeMs`). A queued
message is taken even past the deadline; an expired deadline is one look,
never a park; a wake that finds nothing re-checks the clock and parks for
the time left; a timeout returns one static `Err` (no allocation). No new
traps beyond a non-Int deadline / non-actor sender (programming errors,
same policy as the neighbouring primitives); deadlines clamp, never wrap.

Processes on the kernel's plane (native QOS apps) have no deadline receive
until the plane ABI moves to v7, so there the waits keep each caller's old
pacing: `receiveFromUntil` naps 100 us between looks (std/actor's
`napUntil`), `receiveUntil` sleeps the time left (its callers slept their
whole 16-25 ms period before), `waitInbox` answers `0` and the caller naps
as before. Nothing gets slower or busier on the plane; it gets faster
everywhere else (kernel actors, qosp/Portable apps, hosted builds).

## Callers moved

* `programs/mods/timer.fpr` (hosted mode): the sleeper child and its 10 ms
  slices are gone; the actor waits in `Sys.receiveUntil` on the nearest
  deadline. A shorter deadline takes effect at once and a pending timer
  costs one wakeup, not 100 a second. Hardware mode (CLINT) is unchanged.
* `programs/mods/timedcall.fpr` (new): std/actor's `callWithin`/`callUntil`
  (same wire, same answers) waiting in `Sys.receiveFromUntil`. Used by
  `appclient.fpr` and `appsession.fpr`: every app event, startup, close and
  owner control call. Delete it with the pin bump.
* `programs/mods/appsession.fpr`: startup waits on the mailbox
  (`Sys.waitInbox`); `AS.idle me` replaces the 16 ms idle nap in clockapp,
  diskapp, logsapp, browserapp, termapp and editapp (park until a message
  or 16 ms; still naps 16 ms when a message `next` does not take is queued,
  so never a spin).
* `std/lifecycle.fpr` loop turn and `programs/mods/sysep.fpr` idle turn:
  `Sys.receiveUntil` with their old period as the deadline.

## Measurements (x86-64 KVM box, qosp hosted, 8 harts, median of 3)

| | before | after |
| --- | --- | --- |
| deadline call, same hart (5,000 calls) | 155,063 ns (`AC.callUntil`) | 932 ns (`TC.callUntil`) |
| deadline call, cross hart | 156,661 ns | 2,226 ns |
| 5 ms timer sleep with a 3 s timer pending: mean lateness (40 sleeps) | 5,020 us | -7 us (ms-quantised deadline) |
| same, worst | 5,369 us | 170 us |
| qosp with one 3 s timer pending: voluntary context switches at 2.8 s | 1,543 | 1,401 |

## Left for the fprisc pin bump

* std/actor's own `callUntil`/`awaitReplyUntil`/`awaitFromUntil` in the 87
  files pinned to `std/actor#2de24bf2bdd5cb87` (endpoint clients,
  std/epclient, std/epdeadline, std/blockio, graphics, ...): moving them
  means re-pinning std/actor across the store (19 store versions), which
  belongs with the pin bump that brings `receiveFromUntil`; then
  `timedcall.fpr` goes and its callers return to `AC.*`.
* Plane processes: parking needs plane ABI v7 (fprisc#112).
* Not moved, on purpose: `qos/appside/hal.c` and `hal/virt/blk.c` disk
  waits (they poll a disk-worker / virtio completion flag that nobody
  sends a message for, already with a 10 us spin then a 10-200 us ramp;
  parking them needs a completion wake, not a timed receive;
  `blkWaitInbox` already parks on the mailbox), `std/blockio`'s poll fallback (pinned),
  and `system.fpr`'s service poll (it polls a key, not messages).
