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
are correctness requirements for any later driver simplification. The existing
`MV.MApp` driver adapter and the legacy appkit exports remain during migration;
their presence does not mean the migration is complete.

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

## App session protocol to implement next

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

The app session protocol, migration of legacy plugin service reads, responsive
geometry/focus/input and performance instrumentation remain next steps. The
existing MApp adapter, dynamic plugin exports and other legacy shell effects
are still present; this first slice does not claim the entire shell is pure.
