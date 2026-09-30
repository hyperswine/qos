# Failure honesty: the architecture audit's first step

Date: 2026-09-30. Kind: implementation record.

Step 1 of [the architecture audit's convergence order](2026-09-29-QOS-ARCHITECTURE-AUDIT.md#recommended-convergence-order)
is: fix the concrete loader, RPC and persistence findings, with failure-path
regression checks. This page records that work. The runtime and std/actor
half is in fprisc's `docs/2026-09-30-FAILURE-HONESTY.md`.

## RPC: refused, dead, or answered

Before this change, the helpers did `_ = send ...` and then waited. QSys
and AppKit waited with a plain `receive me`, so any queued message could be
read as the reply. A refused send, or a service that had ended, left the
caller waiting for ever.

Now every request/reply helper goes through fprisc's `std/actor`:

- **`call`**, a correlated protocol. The request is `(me, id, q)` and the
  reply is `(id, r)`. It returns `Ok r`, `Err "mailbox full"`, or
  `Err "dead actor"`. The last covers a service that had already ended and
  one that ended before answering, which the runtime's new
  `receiveFromRes` makes an answer.
- **`sendAwait`**, for the storage `Rpc` wire. That wire is bound by C
  (`Sys.bindStore`, `qos_store_call`) and pinned inside `qlog#c8efd70b`
  through `svc#92a791a3`, so it keeps its shape. The send is checked, and
  the next message from the storage actor is the answer or `Err "dead
  actor"`. The storage actor sends its callers nothing but replies, so no
  correlation id is needed there.

| Site | Now |
|---|---|
| `mods/qsys.fpr` `call` | `AC.call`. Every qsys service (registry, log, file, files, apps, vfs) destructures `(replyTo, id, q)` and answers with `AC.reply (replyTo, id)`. |
| `mods/qsys.fpr` `rpc` | `AC.sendAwait`. A failure is `Err "storage service: ..."`. |
| `mods/qsys.fpr` `relay` | An owner that refused or ended is answered in text: `unavailable: the service for this path dead actor`. |
| `mods/appkit.fpr` `call` | `AC.call`. `vfsRead` / `vfsWrite` / `vfsList` answer in the text protocol's own terms (`vfs unavailable: ...`), the way `no such path` already was. `logAdd` returns `-1` when the log service could not take the line. |
| `std/fs.fpr` `rpc` | `AC.sendAwait`, with the same error wording as qsys. |
| `std/loader.fpr` clients and server | `AC.call`. The server threads the return address `(from, id)`. |
| `std/uart.fpr` `rpc`, `std/timer.fpr` `sleep`/`ping`, `system.fpr` `uartCall` | The send is checked and the wait answers. An ended UART or timer service is a named panic, or `ping` returns 0, instead of a hang. |

Plugins and the shell must be rebuilt together, as for any appkit edit.

Not changed:

- `mods/svc.fpr` `storeRpc` and `system.fpr` `storeRpc1` still wait with
  `receiveRes`, which takes the next `Result` from any sender. Changing
  `svc.fpr` changes its hash and with it the `Rpc` tid that the pinned
  `qlog` uses, so it needs the bottom-up re-commit
  (`./qos.py commit`, move the pins, `./qos.py lock`). It is left as the
  named next step.
- Timer and UART themselves (`mods/timer`, `mods/uart`, both pinned) still
  answer on the uncorrelated `(me, msg)` envelope. `TFire` is both an event
  and the only reply of `TAfter`.

## Persistence: success only when it happened

- **`fileWr`** updates its cached body only when storage answers `Ok`. A
  refused append is reported and leaves the body as it was. The file actor
  also no longer caches `""` when its first replay fails (`okOr ... ""`).
  Until a replay succeeds, reads say `read failed: <path> (...)`, writes are
  refused, and each new request retries the replay.
- **`lManifest`** returns the append's result. When the `sys/live` append
  fails, `lLive` detaches the table it just attached, keeps the old chain,
  and replies `Err "loader <id>: sys/live not recorded (...); the load was
  rolled back"`. The reply and the new chain now follow the record, so the
  running set is always what a reboot would replay.

A pre-existing break found on the way: `tests/qsys.fpr` no longer compiled
against the current compiler. The signature-generality check rejects
`... -> b -> a` for handlers that match `Ak`. Those signatures now say
`AK.Ak`. The test is still not a `check-all` leg; it was run by hand (two
boots, persistence included).

## The native process slot

Two changes, both in `loader/process.c`:

- **Occupancy before any write.** `Sys.placeImageAt` used to clear the
  static window and copy/zero the image (`fpr_qaimg_place`) before it
  checked `g_shared_live`. A second placement could therefore overwrite a
  running image before it returned "a process is still running in the
  slot". The slot is now claimed atomically first, and the check comes
  before anything is written. A failed placement releases the claim.
- **Quiescence at root exit.** `proc_root` used to free the slot (`on_exit`)
  while the process's other actors could still be running slot code, and
  before `proc_root` itself had returned. The slot is now reusable only
  when no actor with the previous process's pid is alive or still switched
  in on a hart (`fpr_pid_live` in fprisc's `runtime/actors.c`). Otherwise
  the placement is refused with the count. Nothing is killed: a process
  whose child actor never ends keeps the slot, and every launch says so.
  Enforced structured shutdown is the alternative rule; it is not taken
  here.

Out of scope: references into the old image that outlive its actors. A
message still queued somewhere that points at the image's statics is the
case that matters, because statics are not deep-copied.

## Tests

| Test | What it proves |
|---|---|
| `tests/qsysfail.fpr` (`./qos.py run`) | A refused append leaves the body unchanged. Storage that has ended is reported, and the body is unchanged. A file actor that never read its body says so and refuses writes. An ended service is `Err "dead actor"`, directly and through the vfs relay. A full mailbox is `Err "mailbox full"`. An event queued by another actor is not read as the reply and is still there afterwards. |
| `tests/loaderfail.fpr` (`./qos.py run`, plugin `sysed1`) | A load whose `sys/live` append fails is refused and rolled back: no export bound, empty chain, and a fresh loader replays 0. |
| `tests/nativeslot.fpr` (test kernel, QEMU) | A second placement while a process runs is refused and the first process's result is intact. A process whose main returned while its child still runs keeps the slot until the child ends. |
| existing `tests/qsys.fpr`, `sysdisk`, `apps`, `selfhost`, route and timer legs | The happy paths are unchanged. |

`qsysfail`, `loaderfail` and `tools/nativeslot-check.sh` are `check-all.sh`
legs. Against the old `loader/process.c`, the nativeslot kernel panics with
`heap exhausted (no block for a slab)`: the second placement overwrote the
live image. `make -C qos native` takes `SYSTEM=` (the kernel program) for
the test kernel, and `tools/build-process-app.sh` takes `KERNEL=` (the elf
an image is linked against).

`check-all.sh` on macOS, 2026-09-30, before the three legs above were added:
105 legs, 98 pass. The same 7 fail with the unmodified compiler and tree:

- the four known on 2026-09-19 (`both.sol`, `mlpipe`, `nn`, `RVV`);
- three that broke between then and now, independently of this work: the
  sketch tier (under `fpr sol`, `paths` and `hello` print nothing with the
  unmodified compiler too; cause not investigated), Sol JSON + CSV, and the
  Sol text-tool leg.
