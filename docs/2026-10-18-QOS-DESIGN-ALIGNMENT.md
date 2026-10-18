# QOS design alignment: ownership, contracts and composition

Date: 2026-10-18. Kind: implementation record and ordered work queue.
Baseline: QOS `cc0334a`, FP-RISC pin
`905c4f42b143a14976e2170cd9d38f2f487ac16e`.

The [recent additions audit](2026-10-18-RECENT-ADDITIONS-AUDIT.md) identifies
concrete gaps in Main, the Editor and hosted programs. Improve those paths
against the original [QOS architecture](2026-09-29-QOS-ARCHITECTURE-AUDIT.md)
and [reliability obligations](2026-10-06-FP-RISC-QOS-Reliability-Draft.md), using
FP-RISC's [style direction](../../fprisc/docs/2026-10-03-STYLE-DIRECTION.md),
[source conventions](../../fprisc/docs/2026-09-01-STYLE.md) and
[value semantics](../../fprisc/docs/2026-10-17-VALUE-SEMANTICS.md).

## Rules for the work

- Keep policy and admission in FP-RISC; native code supplies mechanisms and
  system/library adapters. A limit is named policy with a failure result.
- Keep apps as immutable MVU functions. Their effects are data. A service
  owns a linear resource; a model holds an address or immutable snapshot.
  Inspection consumes and returns the owner. There is no borrowing scheme.
- Validate ordinary input with `Result`. Put refinements on internal numeric
  invariants, checked measures on finite recursion, and enforceable work and
  allocation bounds on pure decision/arithmetic cores.
- Define identity, admission, cancellation, stale completion and cleanup at
  protocol boundaries. Caller resolution and physical reclamation are separate.
- Preserve behavior through executable checks. Record intentional changes and
  checker limitations; compilation alone is not acceptance.

## First implemented slice: hosted timer ownership

`std/hosted.fpr` now keeps a linear `PSt` containing the timer pool. The
application's model and its `update`, `view` and `subs` interface stay ordinary
values. `std/hostedtimers.fpr` owns every acquired timer in a linear chain.
Its inspections return the successor owner; no `keep`/`drop` copies an owner.

Each update validates the requested subscriptions, cancels removed workers,
interprets commands, and acquires missing subscriptions. An unchanged
`(period, message)` retains its worker; duplicate declarations share one.
Removing and re-adding a subscription creates a new token. A queued old
notification cannot reach `update` after its token has been retired.

`After` and `Every` share one admission budget. An `After` releases its quota
when its notification is consumed. A repeating worker queues one notification,
then waits for the host's acknowledgement before another sleep. A slow app
therefore coalesces elapsed periods rather than accumulating repeated ticks.
This is a deliberate change from the old unacknowledged periodic sender.

The resource states are:

| State | Owner, events and exit |
|---|---|
| Sleeping | Pool owns the worker/token; parked slices check owner liveness. Removal or shutdown requests `kill`. |
| Notification queued | Same quota remains held. A repeating worker waits for acknowledgement or owner death; a one-shot worker can end. |
| Delivered | The host matches an owned token. A repeat is acknowledged and retained; a one-shot is consumed. |
| Retired | Token is absent and late notifications are ignored. Runtime reaping of killed actors may still be pending. |

Normal quit and admission failure consume the pool and cancel all retained
workers, including those acquired before a later failure. A worker also exits
if the owner dies while sleeping, or through death-aware receive while waiting
for acknowledgement. The owner-check interval bounds scheduled sleeping
between checks; scheduler fairness is still an assumption, not a real-time
deadline or immediate physical-reclamation guarantee.

### Bounds and failure behavior

| Quantity | Contract |
|---|---|
| Timer budget | `H.defaults.maxTimers = 32`; configurable to 1..1024 with `hostWith`. Counts outstanding `After` and unique active `Every` workers together. |
| Subscription declarations per update | At most the configured budget, including duplicate declarations; conversion/validation stops at exhaustion. |
| Owner checks | `H.defaults.checkMs = 50`; configurable to 1..1000 ms. |
| Delay / period | `After`: nonnegative; `Every`: positive. Direct constructors are validated before acquisition. The full duration stays in milliseconds; only slices of at most 1000 ms are converted, avoiding overflow without an arbitrary duration cap. |
| Sleep slice conversion | `hostedtime.microseconds`: work <= 1, allocation <= 0. |
| Sleep slice calculation | `hostedtime.slice`: work <= 3, allocation <= 0. |

Work is the compiler's abstract operation count; allocation is requested cell
bytes. These four scalar claims are compiler checked. They are not whole-app
WCET or memory proofs. Subscription equality still depends on message size;
file-request queues, stale messages across many retired generations, arbitrary
app callbacks, actor stacks and runtime reclamation need separate bounds.

`tryAfter` and `tryEvery` return `Result` for user-entered values. `after` and
`every` carry refinements for internal calls. Imported refinements may require
runtime checks in this compiler, so tests execute invalid calls and require
named contract blame. They do not equate check-only acceptance with proof.

`hostWith H.defaults ...` returns `Result Unit String` after cleanup on quota,
configuration or protocol failure. The existing `host` entry converts its
error to the program's captured failure. Invalid raw durations used to be
silently clamped; they are now refused. Quit ends interpretation at that
command, and later commands in its list do not acquire resources.

Finite chain/list traversals have checked structural measures, including
command interpretation and pending-answer lookup. The trust list names the
persistent host/worker loops and reviewed acquisition boundary; it does not
grant an application callback a safety exemption.

The internal `ToProgram` type gained `TimerFired`. Rebuild Main, Editor and
hosted program packages together before deployment. There is no C HAL ABI
change. This implementation has not been deployed to a Pi or other board.

### Acceptance

Run `python3 tools/hosted-timers-check.py` (also registered in `check-all.sh`).
Set `FPRISC_ROOT` to a separate copy of the pinned toolchain when the sibling
checkout has unrelated work. Optional `--output DIR` retains logs and results.

The suite checks the arithmetic bounds and deliberately insufficient bounds;
compile-time refusal of duplicated, discarded, projected-away and stale pool
owners; runtime refinement guards; timer cancellation, unchanged/duplicate
subscriptions, changed periods, stale notifications, re-subscription, slow
recipients, quota reuse, 200 acquisition/removal cycles, sleeping/acknowledgement
owner death, partial initialization failure, first-resize behavior and normal
quit. The actual hosted loop and existing app-session suite run with one and
four local scheduler workers.

Local acceptance on 2026-10-18 passed: six ownership refusal fixtures, nine
executed/refused refinement violations, the four scalar bounds and a deliberate
under-budget refusal, the unmarked unsafe callback refusal, and the timer and
app-session suites with one and four workers. A final shutdown case holds both
an outstanding `After` and an `Every` before Quit and verifies reclamation.
The Editor's real compiler/package/process regression (`tests/runprog.fpr`)
also passed with one and four workers. Main and all six app entrypoints passed
check-only compilation; the existing 245 pins passed `lock --check`.

Evidence is retained in `.qos/validation/qos-contracts-20261018/`: the source
snapshot and hashes, clean pinned compiler source, `acceptance/results.json`,
scalar/guard logs, final shutdown logs, entry checks and Editor-run logs.
The snapshot is the baseline above plus this batch's changes. Concurrent
runtime/build and FreeBSD work in the shared checkout is excluded from these
results and preserved in place. The complete `check-all.sh` and board execution
were not run for this batch.

## Next slices, in order

| Slice | Acceptance before calling it complete |
|---|---|
| File endpoint leases and cache reclamation | Closed/dead clients release leases; idle per-file actors can retire without killing another client's open connection; opening more than 64 distinct files sequentially succeeds while simultaneous opens stay bounded. Test stale handles, wrong clients, deletion and reopen races, deadlines and uncertain writes. |
| Main app job ownership | Replace raw endpoint tuples/uncertain-open flags with owned connection/session states. Late open results retain a cleanup owner; timeout cannot authorize reuse. Test owner death and failed close. |
| Editor/compiler protocol | Compiler emits structured entry and diagnostic metadata; valid tabs/multiline definitions run without source-line heuristics. Move runtime compilation/publication behind native library APIs rather than Python/process orchestration. Preserve confinement and publication checks. |
| Terminal pure parsing core | A measured lexer/parser handles quoted separators and escapes, with refined cursor/token bounds and `Result` diagnostics. Retain URL endpoint effects as commands; do not add special path bypasses. |
| Main policy and admission | Pass explicit memory/recovery/file-access policy through one configuration seam. Base runnable budgets on admission/accounting rather than a fraction of physical RAM. Refine counts and indices in pure update cores. |
| Cross-profile evidence | Run the changed service contracts on Native and Portable, then relevant physical boards. Extend the bounds register and lifecycle evidence without claiming a focused host pass proves target parity. |

Each slice should remove a verified gap and add positive legal compositions
alongside refusal/failure tests. Whole-application resource accounting and
ownership-checker soundness remain separate, broader work.

## Implemented 2026-10-18: file leases, entry scan

File endpoint leases (`programs/mods/qsys.fpr`): per-file actors track
`(handle, client)` leases. Reads/writes with an unknown handle or one
another client holds are refused (`"no such handle"`); close stays
idempotent; dead clients are swept on every message; the last close ends
the actor and its cache is re-read from storage on the next open, so the
manager's 64-live-actor budget counts live files. `filesDelete` only
kills a live actor. Deliberate contract change: a reopen after storage
died replays honestly instead of serving a retired cache
(`tests/qsysfail.fpr` leg 2 now expects `"read failed: ... dead actor"`).
Regression: `tests/qsysfail.fpr` legs 8-11 (stale/wrong-client refusal,
retirement on last close, 70 sequential open/close pairs, 64-held bounds
the 65th and closing admits it again) -- `qsysfail: HOLDS` on Portable.

Entry scan (`programs/mods/runprog.fpr`, used by the Editor's
`package`/`runIt`): `hasMain`/`hasApp` recognise a top-level definition
-- name at column 0 followed by `=`, `:`, blank (space/tab/CR), or end
of line with `=`/`:` on a later line. Tab separators, split bindings
and signatures count; `mainfoo`, indented uses, comments and bare uses
do not. The scanner's exact bodies execute green standalone
(`scancheck: HOLDS`, base profile); the new `tests/runprog.fpr` legs
(unit cases plus live tab/split runs) compile clean but the full QOS run
needs the host compiler daemon, which this sandbox cannot start
(AF_UNIX bind is refused).

Remainders: compiler-emitted structured entry/diagnostic metadata and
the native library-backed compile service (this scan accepts what the
front end accepts but is still a scan); TTL eviction for handles whose
dead owners are never followed by another message to that file; the
`qsys` two-boot script currently fails identically with and without this
batch (pre-existing, under investigation separately).

## Implemented 2026-10-19: lease retirement race, dead-client slots

Two faults in the 2026-10-18 lease work (`programs/mods/qsys.fpr`):

- **Open/retire race.** A file actor ended itself on its last close while
  the manager could already be forwarding a new `Open` to it; that open
  went to a dead actor and the client got no answer (4 harts: 3 of 200
  cycled opens lost). Retirement is now asked of the manager: an actor
  that becomes idle sends the manager an idle note (from a one-shot
  relay actor, so it cannot be mistaken for a reply), and the manager
  retires it with a synchronous `Timed`/`Close -1` call. The actor
  agrees (and ends) only if the call comes from its manager, it still
  holds no lease, and at least a second of the deadline remains; it
  refuses otherwise and keeps serving. Because the manager is blocked
  in that call, no `Open` can be in flight to the actor when it ends,
  and the manager drops the URL from its table before serving anything
  else.
- **Slot leak on client death.** Leases whose client died without
  `Close` were swept only on the next message to that file, so 64 dead
  holders on 64 files exhausted the budget forever. Sweeping that
  empties a file now raises the idle note too, and when an `Open` hits
  the 64-file budget the manager first asks every live actor to
  retire (`filesReclaim`) before refusing.

Regression: `tests/qsysfail.fpr` legs 12 (64 holders die without
closing; the 65th open succeeds) and 13 (4 clients x 50
open/read/close on one file; every read answers and the owner is
retired afterwards). On the previous code leg 12 fails on 1 and 4 harts
and leg 13 fails on 4 harts; with this change `qsysfail: HOLDS` on 1
and 4 harts (Portable, riscv64 Linux host under qemu-user, since the
x86-64 backend's six-argument limit rejects `qsys.fpr`).

Residual, by design: lease owners are the client keys the client
*claims* in its message; the actor IPC exposes no authenticated sender
of a `receive`, so a client can still name another client's key and
act on its handles. Closing that needs the runtime to expose the
sender (an fprisc/IPC change), not a qsys change. A forged idle note or
retire request can at most retire an actor that holds no lease. The
manager's 2 s deadline against the actor's 1 s margin leaves a
documented window in which a refused retire is reported as such.
