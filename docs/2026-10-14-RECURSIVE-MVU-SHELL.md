# Recursive MVU for Main - 2026-10-14

Main's shell, applications and nested UI components should use recursive
Model-View-Update, ordinary functions and explicit messages. Lifecycle and
effects are protocols and data, with no registered hooks or lifecycle callbacks.
Most policy belongs in FP-RISC. Hardware access, context switching, atomics,
accurate presentation timestamps and OS configuration remain platform mechanisms.

## Contract

An update consumes a message and a model, returning a successor model and
command values. A view consumes a viewport and that model, returning view data.
Neither performs service I/O. A recursive effect interpreter executes commands
and delivers result messages to the model owner. Children compose by wrapping
their messages and delegating to ordinary child update/view functions.
Independent services/jobs use owned recursive receive loops; nested widgets
can share their parent's loop. Commands, models and messages carry data and
explicit capabilities, not captured application callbacks.

Preserve the existing MVU driver's per-turn memory reclamation, received-root
ownership, persistent render worker and bounded service conversations. Those
are correctness requirements for any later driver simplification. The existing `MV.MApp` driver adapter remains during migration. Main no longer
dispatches the onboard apps through legacy appkit function tables; other
legacy applications and shell effects remain outside this slice.

## Delivery order

1. Move the built-in Files and Logs snapshots out of rendering. Add nested pane
   models, explicit load/result/cancel messages, Loading/Ready/Failed states,
   Refresh/Retry and Home. Retain the last successful rows on refresh/failure;
   correlate results with a generation and ignore obsolete replies. A failed
   read must leave navigation/rendering available. Reads are safe to retry;
   never automatically replay writes with uncertain outcomes.
2. Migrate onboard apps to the same model/effects discipline. Replace
   `appInit/appUpdate/appTree/appVals` dynamic dispatch with a versioned startup
   handshake and app-session messages carrying input and view data. `Close`
   transitions through `Closing`, cancels owned work and waits for bounded
   acknowledgements before `Closed`. Cleanup is explicit ownership, not a hook.
   Cooperative actors still share a process; this does not provide trap isolation.
3. Make viewport, focus, pointer and scroll state explicit in the recursive
   models. Derive layout and hit regions from the same viewport. Validate the
   panel plus 720p/1080p output and keyboard, mouse and supported touch input.
4. Collect timing samples, distributions and diagnostic views in FP-RISC.
   Obtain input/presentation timestamps and GPU counters at the platform
   boundary. Record CPU policy with benchmarks; governor configuration belongs
   to the host. Renderer failure needs retained diagnostics and supervised
   restart because an unavailable renderer cannot display its own error view.

## First slice and acceptance

The first slice covers the built-in Files/Logs panes. Files requests the
namespace's existing `NsList "/"` read-only protocol directly, avoiding an
endpoint handle for a listing. Logs captures the runtime ring outside view.
Logs refresh through paced tick messages while Ready, with no overlapping
read; failure waits for explicit Retry. A pure loading-turn fuse also covers
a lost completion while the UI remains responsive. A pane owner reuses a
persistent worker for completed reads/errors; cancel/replacement stops an
in-flight worker,
and shutdown stops the worker before the shell's existing service barrier.
The model's request generation is authoritative even if a completed result
was queued before cancellation.

The current MVU port carries string-pair messages. A narrow, validated adapter
encodes the pane generation/source and result into that existing transport;
the pane update itself consumes ordinary result/message data. This adapter
is temporary infrastructure, not a new general application callback API.

Acceptance requires executable checks of successful reads, live-peer timeout,
dead-peer failure, explicit retry, retained rows, stale completion after Home
or replacement, scroll behavior without I/O, cancellation and worker cleanup.
Real GL regression checks must cover normal navigation and existing bounded
render failure/shutdown behavior. Physical Pi validation and redeployment are
separate steps; a host check alone does not establish those outcomes.

## App session protocol

The module loader may enter an app once through its normal startup entry.
After that, app-specific function pointers do not cross the session protocol.
Startup negotiates a protocol version and passes only approved capabilities.
The app owns its model and invokes its ordinary named update/view functions.

Session messages should identify the session generation and request/revision:

- `Started`: acknowledges startup and the negotiated protocol version.
- `Input`, `Tick`, `Resize`: facts delivered to the app's update loop.
- `View`: data describing a revision of the app's view, consumed by the shell
  compositor. Service reads happen through commands and result messages before
  that view is constructed; the compositor never invokes app service code.
- `Close`: transitions the app to Closing, stops new work and cancels owned
  jobs/subscriptions. `Closed` acknowledges bounded cleanup and reports failure
  explicitly. A forced stop is distinct from confirmed cleanup.

The shell rejects stale session/revision messages after close or replacement.
Nested UI uses child models/messages and ordinary function delegation. Preserve
the distinction between cancellation, confirmed completion and an uncertain
write outcome. Protocol validation and cooperative actors do not provide
process or memory isolation; a same-process trap remains a separate boundary.

## Implemented and verified first slice

`programs/mods/panemvu.fpr` implements the child model/update/commands without
service I/O. `panejobs.fpr` interprets commands using an owner and a persistent
reader. The shell now renders cached Files/Logs rows, offers R/left-click
Refresh or Retry and Esc/right-click Home, rejects obsolete completions, and
retains the last successful rows during refresh/failure. Logs refresh through
tick messages while Ready; failed reads wait for explicit retry. Successful
reads reuse the same actor. An idle reader observes its owner's death through
`receiveFromRes`; Stop acknowledges after cancelling its owned reader.

Validation used QOS base `c6903c2` plus this slice and the exact FP-RISC lock
pin `bfbdd8dea2c0b9cc2ab39801e060092e2069aa66` in isolated clean checkouts:

- `tests/panemvu.fpr` passed on macOS/AArch64 with one/four workers: pure
  state transitions, retained rows, stale/wrong-source replies, validated wire
  decoding, paced refresh, lost-completion fuse, service refusal/retry, live
  timeout, dead peer, cancellation, shutdown, reader owner death, and 32
  successful reads through the same worker. A cached Files view also runs
  with no namespace capability, proving that path no longer performs I/O.
- `tools/guishell-check.py` passed with four workers and real macOS GL: both
  Main boots, loaded Clock/Browser, archive refusals, Files/Logs scrolling,
  graphics death, live render-worker deadline, storage drain and readiness
  cleanup. A test-local namespace refusal rendered a visible error; R retried
  successfully, Home remained usable, and normal shutdown completed. Failure
  and recovered screenshots were inspected. No production fault hooks were
  added. The first sandboxed run could not bind the local listener; the final
  suite ran with local network/GL access.
- The same AArch64 pane archive passed under the physical Pi's installed host
  with one/four workers: exit zero, no signal, timeout or kill escalation,
  approximately 0.45 seconds per run. Archive SHA-256:
  `dc1fbe7610bbbbd1c1c18ac5856e610efe2470329aeb51c28748f71366982d9f`.
- Normal Main also passed an isolated four-worker Pi EGL/V3D workload with a
  separate writable disk: three Files/Logs/Browser cycles over 70.6 seconds,
  normal quit, then a separate 30.1-second SIGTERM boot. Both exited zero
  without escalation. Sampled RSS was 44,100-45,684 KiB; process maximum was
  49,840 KiB. CPU was 600 MHz. The installed session owned the display, so
  candidate rendering was offscreen. Installed state remained
  `running pid=329 restarts=0`; its writable disk/session were not replaced.
  Candidate shell SHA-256:
  `cb7bed935bc66f0583d820de3c8053a125eec146112638c0cb088defef60e9ba`.
  Installed host SHA-256:
  `d4676ae31a4829323f55847dbc8d6f0e96cd8815fadcf784dda3976750a7ac2d`.

The standard Pi bundle/check now includes `panemvu.qa`. Local ignored evidence
is in `.qos/validation/gui-mvu-20261014/`, including source hashes, GUI logs,
screenshots, Pi contract results and candidate workload results. This is short
functional/ownership validation, not a long-duration memory or performance
baseline. The new GUI is not installed on the Pi by this slice.

## Implemented app sessions

Main now starts Clock, Logs, Browser and Disk through one root `appMain`
export. `appclient.fpr` validates root scope and machine arity, starts the actor,
and exchanges a primitive `(protocol, schema, session/viewport/capabilities)`
bootstrap before sending any `appwire.fpr` constructors. The exact wire module
identity must agree. An unnegotiated actor is force-stopped with cleanup
reported as unconfirmed; even typed Close is withheld until bootstrap agrees. This deliberately requires rebuilding Main and all four
onboard archives together. Legacy archives without this entry are visibly
refused. Existing writable Main disks retain their old app records; rebuilding
only `main.qa` does not migrate those records. Use a fresh candidate disk or
explicitly update its app archives before installation.

Unsafe FP roots have no checked interface stamp. The startup boundary verifies
archive ABI, root scope, arity and protocol/schema agreement; it does not verify
the entry's full type or make untrusted native code safe. A same-process trap
can still terminate the shell. No compiler/runtime changes or native hooks were
added by this slice.

Each app owns its child model and named `init`, `update`, `view` and `step`
functions. The loops use `Sys.loop`, preserving per-turn state ownership and
reclamation. A common transport module accepts data only; it does not register
or call application callbacks. Input, Tick, Resize, read results and Close are
explicit messages. Main sends monotonic sequences and accepts increasing frame
revisions for the active session. App views return scene/text data from cached
models; Main's compositor never calls app-specific functions or service reads.
Logs coalesces severity changes while loading. Browser keeps cached namespace
rows, discards a path result after Back, and admits one read at a time. Disk
uses the passed storage capability for read-only statistics. Loading/failure
status is visible, R retries reads, and Escape returns Home.

Each app owns one persistent read worker. Completed reads and errors reuse that
worker. Commands carry model tokens separately from globally fresh transport
correlation IDs, so queued results cannot impersonate Stop acknowledgements.
Namespace/storage/endpoint reads have 500 ms budgets. A known endpoint receives
a fresh 150 ms Close budget even when its read budget expired. Explicit open
refusals permit retry; a transport failure during open leaves the handle
unknown, blocks further opens in that worker, and reports cleanup as
unconfirmed. The existing namespace Open wire does not propagate the caller's
deadline to every downstream owner. This slice exposes that boundary rather
than treating caller timeout as proof of resource release.

Close enters a serialized Closing turn, admits no new work, waits up to one
second for the read worker's Stop acknowledgement, then reports Closed with its
cleanup result. Main allows 1.2 seconds for app close. It reports forced stop
separately from acknowledged cleanup, latches cleanup failures for the final
shutdown result, and preserves Home/error navigation. Explicit Retry can start
another read-only session after failed cleanup, with at most three such
failures per Main lifetime; exhaustion requires restarting Main. A later good
close cannot erase the retained cleanup diagnostic. An idle or busy reader
observes app owner death; the app observes session-owner death; the session
owner observes shell owner death. Startup without a bootstrap expires after
one second. Shared service shutdown still follows the existing storage drain
barrier. Automatic retry/replay of writes is not introduced.

Responsive geometry/focus/input and performance instrumentation remain next.
The existing MApp adapter, built-in Clock time read, and other legacy shell
boot effects remain; this slice does not claim the entire shell is pure.

## App-session validation - 2026-10-14

Validation used QOS base `0e9c855` plus this slice, the same exact FP-RISC pin
`bfbdd8dea2c0b9cc2ab39801e060092e2069aa66`, and isolated clean checkouts.
`qos.py lock --check` passes with all 238 pins resolvable. The new contract
archives are included in the standard Pi build/check.

- `tests/appsession.fpr` passed on macOS/AArch64 and the physical Pi with one
  and four workers: primitive version/schema rejection, session/sequence
  rejection, cached frames, Close, wrong-session Close, timeout/forced-stop
  distinction, retained cleanup errors, bounded explicit recovery, Browser
  ignoring a late path result after Back, latest-severity coalescing, Disk
  retry, close during a live blocked namespace read, owner death and the
  one-second startup fuse. No native hook/callback API was added.
- `tests/appjobs.fpr` passed on both targets with one/four workers: 32 reads
  through one reader, live read deadline followed by a confirmed fresh-budget
  Close, explicit open refusal with retry, uncertain open reported by Stop,
  and idle/busy worker termination after owner death. Physical Pi runs exited
  zero with no signal, timeout or kill escalation.
- The final `tools/guishell-check.py` run passed with real macOS GL and four
  workers: two boots, all four loaded apps, Browser resolve, Logs severity
  changes, Disk statistics, Clock reopening, visible launch refusal and Home,
  Files/Logs scrolling, graphics death, a live render-worker deadline, visible
  pane failure/Retry and the existing storage drain/readiness cleanup checks.
  Launch-error, Disk and Logs screenshots were inspected. Earlier development
  runs exposed a missing launch-error heading and snapshot bookkeeping after
  the added Home transition; both were corrected before the passing run.
- The final normal Main bundle ran on Pi EGL/V3D with an isolated SD-backed
  disk and four workers: four Files/Logs/Browser cycles over 72.8 seconds,
  normal quit, then a separate 30.1-second SIGTERM boot. Both exited zero
  without escalation. CPU remained 600 MHz. Sampled RSS rose from 53,808 to
  61,432 KiB, with a process peak of 65,276 KiB. This short run does not establish
  a memory plateau or a performance baseline; longer repeated-session profiling
  remains required. The installed service remained `running pid=274 restarts=0`.
  Candidate rendering was offscreen while the installed session owned scanout.

Main archive SHA-256:
`7af864422161765683aaf5e5fd06ad25a10647b9d73b99e703bd9d174e50001e`.
Fresh disk SHA-256:
`283e356c7aedb9f7aa45587559ebb70534c363c75ce288e24e2e48c49bf04ef8`.
Installed compatible host SHA-256:
`d4676ae31a4829323f55847dbc8d6f0e96cd8815fadcf784dda3976750a7ac2d`.

The Pi rebooted during other work before final staging; the candidate was
restaged and the successful hardware runs used one stable boot. No installed
host, GUI archive, seed or writable disk was replaced. Local ignored evidence
is in `.qos/validation/gui-app-session-20261014/`, including source/artifact
hashes, contract results, GUI screenshots/logs and Pi workload results.

## Responsive layout and input

The next slice implements viewport-derived shell/child geometry, explicit focus
and input state, and data-only input messages. Its contract, mechanisms and
fresh validation are recorded in [RESPONSIVE-MVU-INPUT](2026-10-14-RESPONSIVE-MVU-INPUT.md).
