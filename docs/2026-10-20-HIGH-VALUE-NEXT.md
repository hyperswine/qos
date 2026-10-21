# High-value QOS work after runtime preferences

Assessment: 2026-10-20, QOS `d340ecb`. This revisits the original reliability
and usability question after the configuration work. Recommendations below
separate confirmed implementation limits from improvements needing measurement.
No production implementation is included in this assessment.

## What has already moved forward

The old timer-subscription ownership and idle file-actor reclamation problems
have implementation and regression coverage. The whitespace cases from the
October 18 entry-detection audit have also been fixed. They should not remain
on an open-bugs list. The initial runtime-policy/type queue is complete, and
Editor/Terminal preferences now persist on disk. File, app I/O/recovery, launch
and hosted file-access policies still describe themselves as until-restart.

References: [design alignment](2026-10-18-QOS-DESIGN-ALIGNMENT.md),
[runtime policies](2026-10-20-RUNTIME-POLICY.md), and current
`programs/mods/runprog.fpr:93-116`.

## Recommended order

| Rank | Improvement | Concrete benefit | Scope |
|---|---|---|---|
| 1 | Atomic file replacement | Readers and restarted apps see a complete old or new file, rather than a truncate/write gap | Storage and file protocol change; medium/large |
| 2 | Separate compilation from save/recovery work | A long build does not hold up saving the document or recovery copy | App worker ownership and lifecycle; medium |
| 3 | Compiler-provided entry metadata and diagnostics | Editor follows actual language semantics and accurate source locations | QOS plus FP-RISC interface; medium/large |
| 4 | A typed qsh lexer and command representation | Quotes, escaped separators and exact argument boundaries work | Mostly Terminal; medium |
| 5 | A common policy catalogue, settings interface and live refresh | Discover and safely edit all policies; reconcile stale sessions without restarting | Service contract plus UI; staged medium/large |
| 6 | Live endpoint and timer resource policies | Replace the next real fixed operational limits while preserving ownership | Service-by-service medium |

I would start with 1 and 2 for reliability. Item 4 is the smaller visible
usability win. Item 5 most directly advances the goal that QOS can inspect and
change itself at runtime.

### 1. Atomic replacement, beyond application-level safety copies

**Confirmed in source; focused runtime probe described below.**
`programs/mods/qsys.fpr:309-314` tombstones a file when opening it in `replace`
mode. `programs/mods/appjobs.fpr:55,98-110` writes the new bytes later. That
makes an empty-file window part of the current contract, even without a crash.
A writer ending between those operations can leave the destination empty.

Editor `SaveFile` already mitigates document loss with a `.~save` copy and
read-back verification (`appjobs.fpr:58-70`). This is not a claim that it has no
save protection. Ordinary `WritePath`, including routine recovery updates,
does not have that full sequence. The new preference records themselves are
whole snapshots appended to their own keys; they do not use file truncation.

Add an explicit typed replacement operation with a storage commit point. Do
not describe an application-side delete followed by append as atomic. Preserve
old clients and define record/replay/compaction semantics before assigning new
wire behavior. Route ordinary writes, recovery snapshots and document saves
through it once the operation is proven.

Acceptance: interrupt at each write/commit boundary, reopen the disk, and
observe either the entire previous value or the entire new value. Concurrent
readers must never see a partial replacement. Also test storage-full failures,
uncertain acknowledgements, compaction and multi-writer ordering. This is a
proposed contract, not an established power-loss guarantee.

### 2. Compilation must not block document safety work

**Confirmed in source; latency impact not benchmarked here.**
`appsession.fpr:23` creates one app I/O worker. `appjobs.fpr:32-38` executes its
jobs serially; `appjobs.fpr:73-74` calls `Sys.compile` in that worker. Document
saves, recovery writes and worker shutdown therefore wait behind compilation.
Parking the compiler caller frees a hart, but does not free this logical queue.

Give compilation its own owned worker/job stream, with bounded concurrency,
request IDs, admission snapshots and explicit cancellation/completion states.
Keep the existing file-worker endpoint ownership intact. Close must account for
both workers and any host compilation still in progress; merely killing a
waiting actor is not proof that the external compiler has stopped.

Acceptance: hold a compile open deliberately, save and recover a newer document
version, and verify those writes finish independently. Then close or kill the
app and prove that no worker, endpoint lease or unaccounted compilation remains.

### 3. Make the compiler the source of Editor language facts

**Confirmed in source.** `runprog.fpr:71-116` still inserts wrapper source and
scans lines for `main`/`app`. The earlier tab and split-binding cases are fixed.
`editapp.fpr:280-305` still extracts locations from human-readable diagnostics
and adjusts source line numbers. `tools/fprd.py` returns diagnostic text.

Introduce a versioned compile result containing accepted entry kinds,
structured diagnostics and source mappings. Preserve the real compiler's
checking and warning/error semantics; do not implement a second parser in the
Editor. FP-RISC already exposes `Compile.checkedInterface`, but that alone is
not a complete entry/source-map/diagnostic API. Evaluate extending that boundary.
Replacing the entire Python/build-tool bridge can be a later architectural
slice; it is not necessary to deliver the first metadata improvement.

Acceptance: aliases, comments, multiline declarations, imported diagnostics,
wrapper errors, Unicode source columns and warning-only builds agree with the
compiler and point back to the correct user source.

### 4. Give qsh real argument boundaries

**Confirmed in source; focused runtime probe described below.**
`termapp.fpr:79-96` splits `;`, then `|`, then words without quote/escape state.
Quoted separators are treated as syntax, which prevents ordinary commands such
as `echo "a;b"` from expressing their intended text.

Start with typed tokens and a small command/pipeline AST, explicit quoting and
escaping rules, and errors before executing a malformed command line. Retain
the existing namespace operations and command implementations initially.
A dynamic command registry and streaming pipelines are separate later steps.

Acceptance: quoted `;`/`|`, spaces, empty arguments, escapes, variable expansion,
Unicode and unterminated input. A parse error must not accidentally execute an
earlier fragment of what the user intended as one command.

### 5. Make the existing policy system usable as a system

**Confirmed contract gap.** The four service-policy schemas currently advertise
`persistence=until-restart`. `preferencestore.fpr:49,88` requires a stale app
session to restart before adopting newer saved defaults. Schemas, current
values and writes already exist, but their representations and scope differ.

Define a typed catalogue of policy descriptors: schema/version, effective and
saved values, revisions, usage, mutability and application boundary. Build a
small settings view over it, then add explicit reload/reconcile transitions and
persist appropriate service policies. A refresh must validate live input,
history and recovery state; it must not silently discard edits or reset an
ownership counter. Distinguish runtime state from persistable configuration.

Acceptance: discover the policies without hardcoding a UI list; safely edit a
running service; show conflicts and effective-versus-saved differences; refresh
a stale app without losing its document; restart and verify saved values.

### 6. Continue with meaningful resource-policy types

**Confirmed in source.** `epservice.fpr:140-149` fixes the leased adapter at 64
handles, a 2048-byte URL ceiling, 60-second leases and a 10-second default
untimed operation budget. `hostedtimers.fpr:6` defaults to 32 timers and 50 ms
owner checks. Hosted timers already accept configuration through `hostWith`;
the gap is live inspection/reconfiguration, not complete absence of settings.

Add `EndpointPolicy` and `TimerPolicy` with usage snapshots and safe updates.
Lowering a limit must not drop a live handle or timer; lease changes must not
silently renew existing deadlines. Mailbox capacities need a separate runtime
contract: first determine whether resizing is supported, then expose live change
or explicit drain/restart rather than promising arbitrary mutation.

Acceptance: lower-below-use refusals, subsequent admissions under new limits,
lease expiry, timer cancellation, owner death and unchanged in-flight deadlines.

## Further candidates, with different evidence requirements

- **Event-driven idle sessions.** Editor and Terminal still poll several actor
  channels and sleep for 1 ms (`editapp.fpr:765-768`, `termapp.fpr:328-330`).
  A death-aware multi-source wait or explicitly owned event multiplexer could
  reduce wakeups. Measure active/idle CPU and wakeups before assigning a saving;
  retain races involving parent death, worker completion and policy traffic.
  No new Pi or idle-power measurements were taken in this assessment.
- **Transport-authenticated sender identity and system resource admission.**
  Namespace authorization uses the actor ID in the request envelope
  (`epservice.fpr:22-54`); the runtime-policy document explicitly calls this
  cooperative authorization. `runpolicy.fpr:25` also explicitly excludes whole-
  system reservation/accounting. These are important OS boundary projects if
  hostile applications or broader concurrency are intended. They need runtime/
  native work and boundary tests, not additional settings or UI alone.

## Evidence and limits

The focused probe lives under ignored
`.qos/validation/high-value-audit-20261020/`. It uses current QOS sources and a
disposable disk, checks the fixed tab/split entry cases, exercises actual qsh
submission, and opens an existing file for replacement before supplying bytes.
It does not simulate sudden power loss or claim full compiler/native parity.
The installed compiler and Portable host hashes are recorded alongside it.
The probe exited zero on local Portable ABI 22 with one worker, reporting:

```text
entry whitespace regression: fixed
quoted semicolon still splits into commands
replace open exposes empty file before any replacement write
high-value audit: HOLDS
```

The initial make invocation attempted to rebuild the sibling compiler and hit
a sandbox restriction on Cabal's cache log. The probe build instead uses the
existing compiler (`make -o fpr`); no compiler-source edits were made.

The commit preceding this assessment passed the preference regression and
separate-host restart checks with 1 and 4 workers in the preceding task, plus
Main check-only and dependency validation. This task rechecked all 302 pins and
the clean push; it did not rerun the complete sweep, CI, native targets or boards.
