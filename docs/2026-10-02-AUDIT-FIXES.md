# The audit's findings table, closed

Date: 2026-10-02. Kind: implementation record. Fixes the findings table of
[2026-10-02-QOS-AUDIT.md](2026-10-02-QOS-AUDIT.md) and re-pins the compiler.
QOS revision: the commit carrying this page. FP-RISC: the pin in
`fprisc.lock.json` after this change, which includes two runtime changes
made for it (below) on top of the signature and tail-call batch.

## What changed

| Finding | Fix | Where |
|---|---|---|
| Native virtio-net TX spun 4,000,000 iterations on the hart | The sender owns the one transmit buffer (`tx_take`), notifies, spins 2,000 iterations for the usual at-once completion, then PARKS 200 µs between checks; a frame not completed within `NET_DEADLINE` (5 s) takes the network offline and fail-stops the caller; a sender killed mid-frame leaves an orphan the next sender reclaims or times out. The disk's rule, applied to the NIC. | `hal/virt/net.c` `tx_take`, `nic_tx`, `tcp_send`, `handle_arp` |
| Portable launched app images were pid 0 and never freed | `Sys.spawnApp` adopts the attached image its root function lives in (runtime `fpr_image_adopt`); the app installs the reap hook `plug_image_quiet`, which frees the block once no actor of the pid is left, after syscall tag 8 has made the code pages writable again. `Sys.images` now exists on Portable. An image only ever used as a module stays pid 0 and immortal, as before. | `fprisc/runtime/runtime.c`, `actors.c` `a_spawn_app`; `qos/appside/entry.c`; `qos/portable/store.c`, `host.c` `qosp_unload_plugin`; `qos_abi.h` v17 |
| `tests/apps.fpr` hid the leak behind a 97% tolerance | The test waits until `Sys.images` is 0 (bounded) and requires the free bytes back to within 512 KiB of the baseline, the native test's bound. | `tests/apps.fpr` |
| `uartRpc` ignored send refusal and waited uncorrelated | The send is checked and the wait is `receiveFromRes`; a refusing or dead UART service is a `UErr`, so the route answers `IErr` instead of waiting for a reply that was never accepted. | `programs/mods/svc.fpr` `uartRpc`, `uartAwait` |
| `dTimerW` dropped a refused `TAfter` silently | A refused send is `IErr` to the caller. | `svc.fpr` `dTimerSend` |
| `send_or_die` panicked the machine after 1,000 retries | A refused send is `-1` with the reason in the out buffer; the process's `Sys.storeReq` reports it as `Err`. The reply wait is `fpr_receive_from_res_c` on the storage actor, so a dead storage actor is `Err "dead actor"` to the process. | `loader/process.c` `qos_store_call`; `qos/native/proc_entry.c` |
| `fpr_actor_fail` panicked for a routed process image | The scheduler table has a `fail` entry; a loaded process fails through the plane's own `fpr_actor_fail`, which kills the current actor. | `fprisc/runtime/fpr.h`, `actors.c` |
| `runProcessShared` accepted the next `Result` from any sender | The process entry returns its root actor through the boot record; `Sys.placeImageAt` answers `(ok, msg, root)` and the launcher waits with `receiveFromRes me root`. A root that dies without answering is "process failed: dead actor". | `qos/native/proc_entry.c`; `loader/process.c`; `programs/system.fpr` |
| Console output on a blocking descriptor could hold a hart | `qos_console_putc`: `poll` for writability with a 20 ms bound once, then drop and count until the console is writable again, logging both transitions. Descriptor 1 is never made non-blocking (it may be a terminal other processes share). | `hal/unix/hostlog.c`; `qos/portable/haltab.c`; `hal/unix/net_raw.c` |
| `docs/SCHED-MODEL.md` was cited and did not exist | Written as a living register in fprisc, with the bound in admissions as enforced and in time under stated assumptions; the three citations point at it. | `fprisc/docs/2026-10-02-SCHED-MODEL.md` |

The svc module is v1.8 (patch: signature-compatible); qlog re-pins it and is
v2.5; `programs/system.fpr` and `fpr.lock` re-pin qlog. `fprisc.lock.json`
pins fprisc `63d5f11`, which carries the signature and tail-call batch
(`daf0281`) and the two runtime changes above.

One thing learned on the way: `receiveFromRes` answers `Ok <the message>`
or `Err "dead actor"`, so a reply that is itself a `Result` arrives one
level down. The launcher, the test kernel and the kernel's storage
trampoline each read it there now; the first build of this change read
the wrapper as the reply and died in `strcat`.

`tests/nativeimage.fpr` now waits for each process's result by its root
actor, so two processes finishing in either order are told apart.

## Not done

- The Portable application image itself is still fixed-address and
  non-relocatable; only launched plugins are managed memory now.
- The console writer bounds the wait per transition, not per byte: a
  console that oscillates between writable and full costs up to 20 ms per
  transition.
- Disk and net completion are still timed polls, not interrupt-driven
  completions.

## Verification

Run on this Mac at the revisions above. Nothing else was rerun; native
hardware, Linux graphics and the full `check-all.sh` sweep remain as in
the audit.

| Check | Outcome |
|---|---|
| fprisc `check_cases`, `check_sol_tail`, `check_base` (after both commits) | pass; `check_base` 32 legs including `fpr_actor_fail` and process images |
| `./qos.py test` | 12 of 12 |
| `tests/apps.fpr` with appa and appb (Portable) | `APPS HOLD`; the host log shows both images unloaded when their pids ended, `Sys.images` 0, free bytes back within 512 KiB |
| `tools/plugimports-check.sh`, `tools/qsys-check.sh` | HOLDS |
| `tests/uartroute.fpr`, `tests/timerroute.fpr` | routed write and receive, routed fire |
| `tests/storerpc.fpr` | HOLDS (mixed traffic, refusal, death) |
| `tools/nativeimage-check.sh` (QEMU, 2 harts) | `concurrent=both-intact linger=held-then-freed images=0 memory=returned HOLDS` |
| `./qos.py native --smoke` | launcher up |
| fprisc `tests/tpar.fpr` as a native process (QEMU, 2 harts) | `process exited: tpar: ok pid=1 pidsum=8 harts=2` through the correlated wait |
| `./qos.py lock --check` | 8 pins resolvable, lock current |

Not exercised: a stalled virtio-net device (the new deadline path), a
killed sender mid-frame (the orphan path), a full console pipe, and a
refused storage send from a native process. These are the failure
injections the disk tier got in DISK-HARDENING and the net tier still
needs.

## Later the same day: failure injections

The four paths listed as "Not exercised" above now have deterministic tests.
See [FAILURE-INJECTIONS](2026-10-02-FAILURE-INJECTIONS.md) for the exact fault
boundaries, acceptance checks and fresh QEMU/host results. This supersedes that
verification gap; the remaining design limitations above still apply.
