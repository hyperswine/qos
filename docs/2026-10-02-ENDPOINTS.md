# Endpoints: one contract for every URL, and services that claim their own

Date: 2026-10-02. Kind: implementation record and the contract's
specification. Carries out items 2 and 3 of the convergence order in
[2026-10-02-QOS-AUDIT.md](2026-10-02-QOS-AUDIT.md). QOS revision: the
commit carrying this page. Source: `programs/mods/ep.fpr` (the contract,
the namespace actor, the client), `programs/mods/sysep.fpr` (System.qa's
services as owners), `programs/mods/svc.fpr` (the compatibility surface),
`programs/mods/qsys.fpr` (QOS Portable's services as owners).

## The contract

A URL names a resource an actor owns. One actor, the namespace, knows
which actor owns which URL prefix and which process may open what. All
other traffic is four messages between a client and the owner.

**Open.** The client asks the namespace: `NsOpen url mode`. The namespace
authorizes the caller by its pid (the grants it was launched with, a
`/`-boundary prefix of the url with that mode; pid 0, the system itself,
may open anything), resolves the url to the longest registered prefix (a
url ending in `/` is a listing and resolves to `/`), forwards the client's
own request envelope to the owner, `(client, id, Open url mode)`, and
answers the client `Ok (owner, id)` at once. The owner answers the client
directly: `(id, Opened h)`, `(id, Refused why)`, or `(id, Redirect a)`
when another actor serves the url, in which case it has already forwarded
the envelope to `a` and the client waits on `a`. From here on the
namespace is out of the conversation.

**Read, write, close.** `Read h n` answers `Ok v`, an `IoV` (bytes are
`IStr`). `Write h v` answers `Ok v`, whatever the owner says about it.
`Close h` answers `Ok 0`; a read the owner was holding on that handle is
answered `Err "closed"` first. Close is the only cancellation.

**Failure.** Every exchange is `std/actor`'s correlated request `(from,
id, q)` and reply `(id, r)`. A refused send and a dead peer are answers
(`Err "mailbox full"`, `Err "dead actor"`), never a wait. An owner whose
reply is refused because its client has ended closes that handle itself.

**Registration.** `NsReg url owner` claims a url; an exact duplicate is
refused. `NsUnreg url` withdraws it, by the owner only. `NsGrant pid
grants` records a process's grants; the launcher does this at launch.
There is no dispatch table: a new service claims its url with one message
and no edit to System or QSys.

**Listing.** A directory is a read of a url ending in `/`: the lister,
registered at `/`, answers the registered urls under that prefix, one per
line. `ls /services/` is `open "/services/"`, `read`, `close`.

**Trust.** The namespace is the single authorization point, but nothing
stops a program on the same plane from sending `Open` to an owner
directly. This is a cooperative system without hardware isolation, as the
audit says, and the contract says so too.

## What was replaced

- The native router's prefix chain in `svc.fpr` (eight hardcoded
  prefixes, plus two routes outside it) is gone. `Svc.read` and
  `Svc.write`, the surface every app still calls, are the app's grant
  check, then one open, one operation, one close through the namespace.
  Each of System.qa's services is an actor in `sysep.fpr` that claims its
  url at boot: display, keyboard, clock, modules, storage, uart, timer,
  pins. The keyboard holds a read and answers it on close.
- The Portable `sysActor` registry, the `vfsActor` entry table and its
  per-call relay are gone. The log, the storage records, the file
  namespaces and the apps claim their urls in `qsys.fpr`. A file is
  created by the first open for writing: the manager spawns its actor,
  registers the path so the next open resolves to the file directly, and
  redirects the open that created it.
- `appkit`'s `VfsList`, `Read` and `Write` constructors are gone;
  `vfsList`, `vfsRead` and `vfsWrite` are the one-shot conveniences over
  the contract, in the text protocol's terms. `Ak` is `LogAdd` and
  `LogSnap` only.
- The capability record `st` gains `ns`, the namespace. The app-scoped
  storage url `/services/storage/kv` is rewritten to
  `/services/storage/kv/<id>` from the capability before the open, so a
  routed caller still cannot name another app's stream.

## What was added to the runtime

`Sys.pidOf actor` (fprisc `runtime/actors.c`): the pid of an actor, so the
namespace authorizes by the sender of a request and never by anything the
request says.

## Not done (as first published)

- Native process images (loaded under a pid) still reach storage through
  the C syscall channel, not through the namespace; they hold no actor
  handles across the process ABI. `NsGrant` is exercised by the test and
  usable by the Portable loader, but the native launcher does not call it
  yet.
- UART.qa still does not own the console: the display and keyboard
  endpoints drive the 16550 registers themselves, as the router did. They
  are now owners that could be replaced by UART.qa routes without any
  other edit, which is convergence item 4.
- `Svc.read` and `Svc.write` pay three round trips per operation. An app
  that keeps a handle open pays one.

## Later the same day: the three closed

**UART.qa owns the UART.** System.qa touches no 16550 register. The
service is opened, armed and shared at boot; the display endpoint writes
to it (`consoleWrite`: chunks against the outgoing budget, `UFlush` when
the budget is full), and System's own `puts`, `putLn` and `getc` are the
same client, so the boot banner and the permission prompts go through the
service too. The keyboard endpoint subscribes to the service through a
subscriber actor of its own (replies to `UGet` and `URx` pushes must not
share one sender, or a push queued first is read as the reply), queues
what arrives, and while a read is held also polls `UGet` once a
millisecond for the Portable tier, which has no interrupts. The console
exists only after the services do: `con` is now `(uart, ns)`. The
register console helpers are gone from `svc.fpr`.

**A loaded process reaches the namespace.** The boot record carries the
namespace actor (`Sys.bindNs` at boot; `Sys.ns` in the process), and the
launcher reserves the process's pid before placement (`Sys.reservePid`,
the fifth argument of `Sys.placeImageAt`) so its grants are in the
namespace before its first instruction, the `/services/storage` grant
scoped to `/services/storage/kv/<id>`. `tests/epproc.fpr`, run by
`tools/epproc-check.sh` in the full sweep, opens the display and the
clock, is refused `/pins/1` by name, and round-trips its own storage
stream, all through `EP` with its own copy of the module. The C syscall
channel stays for `Sys.storeReq`. The Portable loader records a launched
app's manifest grants under its pid (`serveWith fs ns`) before it sends
the app its first message.

**One round trip for the launcher.** The builtin launcher opens its five
handles once (`capsWithEps`: display, display/line, keyboard,
keyboard/poll, clock) and `svcWrite`, `svcReadKey`, `svcPollKey` and
`svcClock` are one `EP.write` or `EP.read` on them; `Svc` remains the
three-trip path for an app that opened nothing. `tests/kbdread.fpr` holds
a read, takes bytes queued before the first poll one per poll, and polls
empty.

**What it found.** Two bugs outside QOS. The compiler listed a module
reached by two spellings (`ep` and `../programs/mods/ep`) twice in the
unit list, so the link saw its symbols twice; units are deduplicated by
hash now. And the runtime's arena pool override was a hart field: the
launcher, parked in an `AC.call` inside `Sys.loopWith`, let every actor
the hart ran meanwhile allocate into its arena, which the step's end tore
down under them. The keyboard endpoint's queue and UART.qa's own state
were the victims; the override is an ACB field now
(fprisc `docs/2026-10-02-ARENA-OVERRIDE.md`). Both were invisible until
System.qa talked to its services by message from inside the arena.

Verification of this section, on this Mac, with the compiler built from
the fprisc commit the lock pins (`4f1446e`, in a clean worktree; the
Portable host binary itself was built earlier by the same codegen
revision): `./qos.py test` 13 of 13 (epecho included); `./qos.py native
--smoke` with the launcher drawing and taking keys through UART.qa;
`tools/epproc-check.sh` with `process exited: epproc: display=ok clock=ok
ungranted=not granted: /pins/1 (read) kv=ok`; `tools/nativeimage-check.sh`
HOLDS; `tools/qsys-check.sh` two boots; `tests/apps.fpr` HOLD;
`tests/kbdread.fpr` `seq=wxyz00 first=97 second=98 poll=0`;
`tests/pathnotes.fpr`, `loaderfail`, `storerpc`, `qsysfail`, plugin
imports, the three route tests; `./qos.py lock --check` eleven pins.
fprisc's cases and base suites pass on the pinned commit. Modules
re-committed: svc v3.0 (major: the register console helpers are gone),
qlog v2.8.

Not exercised: two clients holding the keyboard at once (the second is
refused "busy"); a Portable app that opens a url through the grants the
loader recorded (the loader path is exercised by `apps.fpr` with a
namespace of 0, the grant message by `epecho`).

## Verification

Run on this Mac at the revisions above. Modules re-committed: ep v1.0,
svc v2.0 then v2.1 (major: `IoV` moved to ep), qlog v2.6 and v2.7,
std/actor v1.0 into this tree's store; ten pins in `fpr.lock`.

| Check | Outcome |
|---|---|
| `tests/epecho.fpr` (new, in the smoke set and `check-all.sh`) | HOLDS: register, open/write/read/close direct to the owner, the listing names the service, unknown and taken urls refused by name, a close answers a held read, an ungranted child refused and a granted one let through, a dead owner refused by name |
| `tests/svcurl.fpr`, `tests/uartroute.fpr`, `tests/timerroute.fpr` | the Svc surface over the namespace: display, clock, keyboard poll, diskless storage, unknown url and wrong shape as data; routed uart write and receive; routed timer fire |
| `tools/qsys-check.sh` | two boots HOLDS (11 paths listed, note bytes doubled) |
| `tests/qsysfail.fpr` (rewritten over the contract) | HOLDS: refused and ended storage, an unreadable file, a dead owner at open, a full mailbox, an unrelated queued event |
| `tests/apps.fpr`, `tests/pathnotes.fpr`, `tests/storerpc.fpr`, `tests/loaderfail.fpr`, `tools/plugimports-check.sh` | HOLD, unchanged |
| `./qos.py test` | 13 of 13 |
| native: `./qos.py native --smoke` | the launcher draws its screen and takes keys through endpoints |
| native: `tools/nativeimage-check.sh`, `tpar` as a process | HOLDS; `process exited: tpar: ok ... harts=2` |

Not exercised: a UART.qa-owned console, two clients holding the keyboard
at once (the second is refused "busy"), and a Portable launch that calls
`EP.grant`.
