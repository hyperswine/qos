# Recent QOS additions: simplifications and hardcoded policy

Date: 2026-10-18. Reviewed QOS `cc0334ad6eb45c7e32ac7c6eb9f9851705a273eb`,
primarily the Terminal, Editor, hosted-program and Pi SDK additions since
`96abe0e`. This is a focused source audit with a local executable probe,
not a complete OS security audit or a new device validation.

Yes: there are deliberate subsets, fixed application policies and some
functional gaps. They should be distinguished from the real compiler,
loader, storage and process mechanisms those applications use.

Implementation follow-up, 2026-10-18: item 1 is addressed by the
[design-alignment work](2026-10-18-QOS-DESIGN-ALIGNMENT.md), with linear timer
owners, cancellation, stale-token checks, admission and lifecycle regressions.
The finding and probe below retain the pre-fix audit snapshot.

## Fix first

### 1. Removed subscriptions keep their timer actors

**Reproduced locally; introduced with hosted apps in `b526cbb`.**

`std/hosted.fpr:183-224` compares the new subscriptions with the previous
list and spawns new tickers. It never cancels removed tickers or records
their ownership. A ticker loops until the process ends. Removing a
subscription therefore does not stop its events; removing and re-adding
the same subscription creates another producer.

An actual QOS-hosted probe called `startSubs` with a long-period timer,
removed it, and re-added it. Live actor counts were:

```text
before=2 started=3 removed=3 resubscribed=4
```

The existing implementation record acknowledges the limitation at
`docs/2026-10-17-PROGRAMS.md:336`. Ignoring stale messages does not recover
the actors, wakeups or queue traffic. Use owned, cancellable subscriptions
and reconcile both additions and removals; test repeated toggles and changes
of period. Retaining an unchanged subscription must not create duplicates.

### 2. The new file-actor bound counts retained caches, not concurrent opens

**Verified in source; the 64-actor guard was added by `4e4847f`.**

`programs/mods/qsys.fpr:394-401` refuses another file actor when 64 are live.
But `Close` at line 240 acknowledges the operation and keeps the actor and
its cached body alive. Consequently, opening and closing enough distinct
files can exhaust this allowance even without concurrent open handles.
Deleting a file ends its actor; ordinary Close does not. This also affects
Editor saves, because creating a safety copy needs another file actor.

Bounding cached file state is reasonable. The missing functionality is
reclamation or eviction of idle actors, supported by genuine handle/lease
accounting. Raising the constant would postpone the problem. This finding
was not stress-tested against storage or the Pi in this audit.

### 3. Editor detects runnable entries by matching source lines

**Reproduced locally; part of the Editor/hosted-app additions.**

`programs/mods/runprog.fpr:95-99` recognises only lines beginning with
`main ` or `main=`, and similarly for `app`. Editor uses those predicates
to choose its wrapper and to refuse Run (`editapp.fpr:248-258`).

Both of these sources passed the actual compiler's front end:

```fpr
main	= 42.  # here the separator is an actual tab
```

```fpr
main
  = 42.
```

The executable probe reported `False` for both through the actual
`RP.hasMain` function. They can therefore be valid FP-RISC but be refused
as having nothing to run. Entry detection should come from parsed/compiler
metadata. Wrapper placement and diagnostics also use textual heuristics
(`runprog.fpr:71-93`, `editapp.fpr:264-298,478-508`) rather than a source-map
and structured-diagnostic interface.

## Architectural and product subsets

### 4. The native Pi compiler service still uses Python and external tools

**Verified in source; the bridge predates this deployment, while the Pi SDK
is new in `cc0334a`.**

The application-side Editor is FP-RISC. Its Build/Run effects go through
`Sys.compile` to a host Unix socket. `tools/fprd.py` is Python and invokes
the compiler and `make` as subprocesses (`fprd.py:101-104,178-181,218-241`).
The SDK includes Python, make, GCC's assembly driver, assembler, linker and
collect2 (`compiler-sdk.py:77-105`); its GNU link command is configured in
`compiler-sdk-run.py:25-40`.

Thus “native” means the compiler executes on the Pi's ARM64 CPU. It does
not mean compilation is a self-hosted FP-RISC service using only native
library APIs. Under the user's no-Python/no-tool-call goal, this remains
unfinished migration work. A first-class compilation/package service with
library-backed compilation and linking would remove that dependency.

The thin `EditorCompiler.hs` delegates to the real `Compile` and `Commit`
modules. It omits the Sol VM and some CLI/backend functionality; it does not
substitute a toy parser or a fabricated successful compilation. The normal
production builder still uses the full compiler.

### 5. qsh is a closed, minimal command language

**Quoted-separator behaviour reproduced; documented intentional subset.**

`termapp.fpr:77-100` splits commands on `;`, stages on `|`, and words on
spaces. There is no quoting or escaping. The actual `T.submit` probe for
`echo "a;b"` ended with `error: b": no such word (help)`.

Commands are fixed cases in `job` and `pure` (`termapp.fpr:129-176`), not a
general command/program registry. Pipelines pass materialised lists of
strings, not streams or typed process channels. `mkdir` creates a `.dir`
marker and directories are URL prefixes. These are real namespace reads
and writes, but this is not yet a general FP-RISC process shell. A lexer,
typed command registry and managed process/stream interface would provide
a more compositional extension path without adding POSIX tool execution.

### 6. Hosted apps use a restricted presentation and effect protocol

**Verified in source and explicitly documented as a subset.**

`std/hosted.fpr:44-84` permits key/resize/message events and a small set of
file/timer/quit effects. Views are `List String`; there is no Surface2 tree
or pointer event in this protocol. Editor clips the displayed view to the
program panel (`editapp.fpr:643-650`). This is narrower than the shell's
recursive GUI app/session protocol.

File authority is also fixed in the Editor: hosted programs can use `/home`,
excluding its own recovery directory, with textual path checks
(`editapp.fpr:404-429`). This is explicit mediation, but not a general
per-program capability/grant configuration. Esc, Shift-Tab, Ctrl-R and
Ctrl-J also remain reserved by the surrounding shell/Editor.

### 7. Application and deployment policies contain fixed assumptions

**Verified in source; different consequences should not be conflated.**

- Run budgets use physical memory divided by four, or a fixed 1 GiB fallback
  (`editapp.fpr:378-391`, `qos/portable/haltab.c:35-38`). This is a policy
  heuristic, not an admission decision based on available application arena
  space or a configurable per-program resource account.
- Editor uses one global recovery path `/home/.editor/session`
  (`editapp.fpr:47`) and an internal clipboard in its own model
  (`editapp.fpr:54,172-180`). This is single-session recovery and in-app
  copy/paste, not an independent clipboard service or multiple recovery
  slots.
- The clock app shows monotonic runtime time, with a stopwatch
  (`appjobs.fpr:25`, `clockapp.fpr:31-38`, `hal/unix/net_raw.c:250-253`).
  It is not a wall-clock/calendar/timezone service. Correcting the Pi's UTC
  during deployment does not change this clock job's semantics.
- The disk migration tool accepts exactly the canonical four- or six-app
  index (`update-main-disk.py:19-20,144-147`). It refuses custom profiles.
  This is a conservative deployment-tool restriction; runtime app discovery
  still enumerates `apps/index` (`qsys.fpr:427-468`). The OS is not limited
  to six apps by that migrator's whitelist.

These policies should become profile/service configuration where wider
generality is intended. Replacing every numeric constant with a setting
would not by itself fix ownership or missing APIs.

## Bounds and platform limits that are not mocked functionality

The 64 KiB captured-console ring reports lost bytes; the 400-line output
history, 200 undo steps and SDK filesystem/heap quotas are explicit limits.
They do not fabricate successful output. Count limits do not automatically
establish a whole-application byte or WCET guarantee, however.

The recent bridge uses a real host worker and parks the caller; builds are
serialised. The app's shared worker also serves saves, so responsiveness
does not imply that a save can bypass an ongoing compile. Native QOS without
the host compiler bridge returns an explicit error
(`qos/appside/entry.c:346-348`). Portable confinement should not be described
as complete native-kernel resource enforcement or hostile-code isolation;
the current implementation record lists the remaining boundary at
`docs/2026-10-17-PROGRAMS.md:258-289,331-344`.

No embedded JS/CSS was found in the new Terminal, Editor or hosted-app
implementation. Their native GUI styling is composed as typed Surface2
values. The successful `42` example is not hardcoded into those applications:
Run wraps and evaluates the submitted `main`, through the real package and
process pipeline. This audit found no added flag bypassing the compiler's
normal safety/type/contract checks in the Editor daemon path.

## Evidence and next work

Local evidence is in the ignored directory
`.qos/validation/recent-additions-audit-20261018/`: two compiler-checked
source examples, `frontend-results.json`, the executable FP-RISC probe,
its native QOS build log and `probe.log`. The probe ran on local macOS ARM64
QOS Portable ABI 22, one hart, with a disposable disk path and networking
disabled. It exited zero. The Pi and its installed services were untouched.

The highest-value functional fixes are cancellable subscription ownership,
idle file-actor reclamation, and compiler-provided entry/diagnostic metadata.
The separate architectural task is replacing the Python/subprocess compiler
pipeline with a native service/library interface. No production code was
changed or fixes applied as part of this audit.
