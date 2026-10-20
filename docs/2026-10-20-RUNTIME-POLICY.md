# Runtime policy and explicit state types

Kind: implementation record and staged design plan. Applies to the working tree
based on QOS `94d1b81`, with the file reclamation and check-all fixes recorded in
[design alignment](2026-10-18-QOS-DESIGN-ALIGNMENT.md). Started 2026-10-20.

QOS policy should be ordinary typed FP-RISC state owned by a live service. A user
should be able to discover its effective values, constraints, usage and revision,
then change it without rebuilding or restarting the system wherever the resource
contract permits. Moving literals into a constants file alone does not achieve
this. The file manager policy, endpoint ownership, and runtime app I/O and
recovery, run admission, and hosted-program file access slices are implemented below. Other rows remain work to do.

## Work queue

| Original source and behavior | Proposed type | Runtime change boundary | Status |
|---|---|---|---|
| `programs/mods/qsys.fpr`: 64 live file actors, 1024-byte new paths, 2000 ms reclamation, 1000 ms retirement margin | `FilesPolicy` (module `filepolicy`, constructor `Policy`) | Atomic manager update; next admission or retirement request, including existing actors | Pushed in `67a9c21` |
| `programs/mods/appjobs.fpr`: read 500 ms, write 2000 ms, delete 1000 ms, cleanup 150 ms; `programs/mods/appclient.fpr` recovery cap of 3 attempts | `apppolicy.IoPolicy`, `RecoveryPolicy` | Snapshot at operation/recovery start; keep original in-flight deadline and cleanup obligation | Pushed in `b9d3b5b` |
| `programs/mods/editapp.fpr`: child memory = physical RAM / 4, fallback 1 GiB | `runpolicy.RunPolicy` | Snapshot after build, before spawn; existing processes retain their admitted budget | Implemented in the Editor policy continuation below |
| `programs/mods/editapp.fpr`: `/home/` access, `.editor/` exclusion and path checks | `fileaccesspolicy.FileAccessPolicy`, `Path`, `Grant` | Each new hosted-program request; retain the captured grant for pending replies | Implemented in the Editor policy continuation below |
| `programs/mods/appjobs.fpr`: `{held=(0,0), uncertain=""}` | Linear `endpointstate.State`: `Vacant`, `Held`, `Uncertain` | Explicit transitions preserving handle ownership and uncertain outcomes; inspect state, never overwrite it with arbitrary settings | Implemented in the continuation below |
| `programs/mods/editapp.fpr`: numeric job and prompt modes | `JobKind`, `PromptMode` | Typed events and transitions; expose current state through app inspection | Planned |
| Storage RPC integer operation tags and string-matched errors | `StorageOp`, `StorageError` | Typed facade plus a versioned wire codec; preserve existing clients during migration | Planned |
| Editor undo 200, output 400, recovery path; Terminal input 240, output 400 | `EditorPreferences`, `TerminalPreferences` | Live updates with an explicit retained-history policy; recovery-path changes migrate or finish current recovery work first | Planned |

Follow-up inventory should include the endpoint adapter's lease lifetime and
handle budget, worker mailbox capacities, timer limits and other service defaults.
This is the initial reviewed list, not a claim that all QOS literals are covered.

## Common contract

Each policy owner should expose schema, current effective values, revision,
mutability, usage relevant to validation, and the point at which changes take
effect. A complete update supplies an expected revision. The owner validates and
commits it atomically; stale edits and invalid combinations leave the entire
policy unchanged. Replies return the effective revision and values. After a
transport timeout, read the revision before retrying: the update may have applied.

Resource reductions must respect current ownership. Refuse a limit below live
use unless an explicit drain or migration operation exists. Never reset usage,
renew an in-flight deadline, discard a live handle, or convert an uncertain write
into a known failure to accommodate a policy edit. These rules follow the
[resource account design](2026-10-03-RESOURCE-ACCOUNTS.md); this file-policy slice
does not implement process memory accounting or general resource accounts.

Fundamental machine, storage and wire limits remain discoverable constraints.
Changing a representation requires migration or version negotiation, not a raw
integer update. The goal is introspection for all such constraints and live
mutation wherever a meaningful safe transition exists. Boot defaults, persisted
preferences and current effective policy must be distinguishable.

## Implemented file policy

`programs/mods/filepolicy.fpr` owns the nominal `Policy`, `Update` and `PolicyError`
types, defaults, validation and strict text codec. `qsys.fpr` carries a `FilesCtx`
through every manager transition. The file manager serializes configuration and
file opens; a leased endpoint adapter forwards the original client and deadline.
Normal disk-backed boot registers these endpoints:

- `/services/file-policy`: read effective values, revision and live actor count;
  write a complete update with the expected revision.
- `/services/file-policy/schema`: read field constraints and effect boundaries.

Example commands for the QOS Terminal, starting at revision 0:

```text
cat /services/file-policy
cat /services/file-policy/schema
write /services/file-policy revision=0 maxLiveFiles=96 maxPathBytes=1024 reclaimMs=1500 retireMarginMs=500
cat /services/file-policy
```

The update format is exactly those five `key=value` fields in that order.
Whitespace and a trailing newline are accepted. Missing, repeated, reordered or
unknown fields, numeric suffixes, negatives and overflow are rejected. The text
codec accepts at most 512 bytes, sufficient for all five machine integers and
labels. A successful update advances the revision even if values are unchanged.
Revision overflow is refused.

| Field | Default | Constraint and live effect |
|---|---:|---|
| `maxLiveFiles` | 64 | Positive; at least current live file-actor count. Controls the next actor admission. Raising it permits more actors; lowering it never evicts an owner. This is not a byte-memory guarantee. |
| `maxPathBytes` | 1024 | 1 through the pinned storage wire's 1024-byte key ceiling. Applies to newly created names. Existing names, including names rediscovered from storage, remain accessible. |
| `reclaimMs` | 2000 | Positive and representable as an absolute microsecond deadline. One shared deadline per reclamation pass; no renewal between candidates. |
| `retireMarginMs` | 1000 | Positive and strictly less than `reclaimMs`. Sent with each retirement request, so already-running file actors use the current value. A missing reply still retains ownership. |

A manager processes an update after its current request finishes. That request
continues under its prior policy. Retirement is a private timed endpoint command;
the file actor checks manager identity, idle leases and remaining deadline before
acknowledging. The older timed `Close -1` entry retains default-margin behavior.
The compatibility `filesMgr` constructor retains default policy for existing
private-manager callers; production boot uses `filesManaged`, which exposes the
live endpoints. Policies are volatile until restart in this first slice; durable
settings and a generic policy browser remain follow-up work.

Writes require the system process (pid 0), matching existing service-admin
conventions. Namespace grants still control discovery/opening for app processes.
QOS IPC currently carries caller-claimed actor IDs, so this is cooperative
service authorization, not authenticated protection against forged raw messages.
Changing that requires the sender-identity work described in the existing design
notes. A dead policy adapter does not transfer policy ownership away from the
manager.

## Validation

`tests/filepolicy.fpr` exercises the production namespace adapter and manager with
a fake storage service: readback and schema, atomic updates, malformed and stale
edits, live admission changes, reductions below use, preserved handles and known
paths, expired requests, current retirement timing on existing actors, the Terminal worker write/read/cleanup path, a shortened shared reclamation budget,
and two concurrent writers sharing an expected revision. The storage reliability runner
includes it alongside the existing reclamation and failure tests.

Validated on 2026-10-20 with sibling FP-RISC
`3206b8469b2de187553750afc5d960f3dd6d53e1` and a matching macOS Portable host:

- `python3 tools/storage-reliability-check.py`: all 12 runs passed (six tests,
  each on one and four workers).
- Final `filepolicy` archive: passed on one and four workers after the last
  deadline-validation and file-write compatibility changes.
- `programs/main.fpr`: Portable check-only passed.
- `python3 qos.py lock --check`: 257 pins resolved and lock current.
- `git diff --check`: passed.

Detailed local logs are in `.qos/validation/live-policy-20261020/`.
These are Portable host checks. Native and physical Pi/STAR64 acceptance and
deployment have not been performed for this slice.


## Endpoint ownership continuation

Started from `67a9c21` after committing and pushing the file-policy slice.
`programs/mods/endpointstate.fpr` replaces the worker's combined sentinel record
with a linear `State`: `Vacant`, `Held actor handle`, or `Uncertain reason`.
The worker moves this owner through each job and cleanup operation. These are
resource states, not writable configuration values: editing a flag cannot prove
that a close succeeded or resolve an unknown open outcome.

`cleanup` consumes the owner and returns both the result and its successor.
Confirmed close produces `Vacant`; failed close retains `Held` for retry.
`Uncertain` refuses further opens while preserving the reason. A separate
`OpenFailure` type distinguishes a confirmed `Refused` response from an
`Unconfirmed` transport outcome, replacing the previous Boolean distinction.
Read, write, append, delete and safe-save jobs all carry the same successor state.

`AW.Inspect` retains its existing diagnostic record shape (`held`, `uncertain`).
The snapshot helper returns that ordinary data plus the successor owner, so
inspection does not copy or discard the linear state. The app wire is unchanged.
Non-endpoint jobs such as Clock remain usable while endpoint cleanup is blocked.

On Stop or parent death, the worker attempts cleanup and returns from its loop.
Its explicit terminal `ended` transition consumes any remaining local owner;
it does not claim that a failed close succeeded. Stop still reports that failure,
and endpoint services can sweep leases belonging to the now-dead worker. Raw
actor/handle IDs remain cooperative IPC data, not unforgeable capabilities.

The follow-up test runner, `tools/endpoint-state-check.py`, checks six compiler
refusals for duplicated, discarded or reused owners, then runs `appjobs`,
`appsession`, `appsessionmemory` and `filepolicy` on one and four workers. It is
registered in `check-all.sh` and the CI service checks. Worker tests now cover
failed-close retention, retries before admitting another open, successful cleanup
followed by an open refusal, inspection compatibility, and an uncertain open
blocking subsequent read/write/delete requests without sending another open.

The runtime app-policy continuation below builds on this ownership model.
Updates affect subsequent operations without changing deadlines or ownership
obligations of work already in flight.


Continuation validation on 2026-10-20: all six ownership misuse programs were
refused, and all eight Portable runs passed (four programs on one and four
workers). The 3000-operation memory regression remained within its existing
8-root / 2 MiB bounds. Main check-only, the four check-all verdict unit tests,
`bash -n check-all.sh`, Python compilation, `git diff --check`, and the 258-pin
lock check passed. Logs are under
`.qos/validation/endpoint-state-20261020/`. This continuation uses the same local
compiler revision as the file-policy validation above; physical-board and native
runtime acceptance remain untested.


## Runtime app I/O and recovery policies

This continuation starts after the endpoint ownership slice was committed and
pushed as `120a7b9`. Main now creates one app-policy owner and a leased namespace
adapter at `/services/app-policy` and `/services/app-policy/schema`.
`programs/mods/apppolicy.fpr` defines `IoPolicy`, `RecoveryPolicy`, `Policy` and
revisioned `Snapshot` types. The owner serializes complete updates, validates
field combinations and arithmetic, refuses stale or expired changes, and returns
the effective policy and revision. Settings last until Main restarts.

| Type and field | Default | Application boundary |
|---|---:|---|
| I/O `readMs` | 500 | Next file read, namespace listing or disk query |
| I/O `writeMs` | 2000 | Next write or append phase |
| I/O `deleteMs` | 1000 | Next delete phase |
| I/O `cleanupMs` | 150 | Each cleanup attempt under the job's snapshot |
| Recovery `maxFailures` | 3 | Next launch admission; zero disables launches |
| Recovery `startupMs` | 500 | Next startup handshake |
| Recovery `responseMs` | 500 | Next event/response exchange |
| Recovery `closeMs` | 1200 | Next app close, including its worker shutdown |
| Recovery `workerStopMs` | 1000 | Worker shutdown within the app close deadline |

Example, after reading the current revision (the example assumes revision 0):

```text
cat /services/app-policy
cat /services/app-policy/schema
write /services/app-policy revision=0 readMs=750 writeMs=3000 deleteMs=1500 cleanupMs=250 maxFailures=5 startupMs=750 responseMs=750 closeMs=1800 workerStopMs=1500
```

All ten fields are required in this order. Decimal parsing is shared with the
file-policy codec in `policytext.fpr`; overflow, suffixes, duplicates, omissions
and extra fields are refused. Durations must be positive and fit the derived
microsecond deadline. `workerStopMs` must be less than `closeMs`. As with file
policy, writes use the existing cooperative system-process authorization.

Each worker fetches one snapshot before a job, retaining it through every phase
of a safe save and through endpoint cleanup. A policy edit cannot renew the
running operation's deadline, discard a held handle or clear an uncertain open.
A later job can use a larger cleanup budget to retry a retained handle. Stop
uses the last admitted job's cleanup policy while draining that job. Shutdown
budgets may still force a longer operation to stop; an unconfirmed cleanup
remains an error rather than being reported as successful.

Each app-client lifecycle command also uses one snapshot. The caller obtains it
from the session owner and sends it back with the command, so both use identical
values despite concurrent configuration changes. The caller's derived wait is
`2 * closeMs + startupMs + responseMs + 250` milliseconds, covering old-session
close, startup, response and possible failure cleanup. The owner passes the
absolute close deadline and worker-stop budget to the app. No fixed 2500 ms
caller timeout overrides larger configured lifecycle budgets.

Failure counts remain in each session owner and saturate at the machine integer
maximum. Raising the cap admits subsequent attempts without clearing history;
lowering it blocks subsequent launches without rewriting existing counts.
`AW.InspectPolicy` exposes a worker's last admitted typed snapshot without
changing ownership. `AP.Inspect` includes failures, the last admitted cap and
policy revision, and remains available when the policy service is unreachable.
A configured policy service that is unreachable produces an explicit error;
only an explicit policy owner of zero selects standalone defaults. This mode
preserves existing isolated worker/client constructors and tests.

The control-plane query budget remains a named, introspected bootstrap constant
of 250 ms. The initial app receive has an introspected 1000 ms bootstrap bound
before the app knows its policy-owner address. These transport bootstrap bounds
are not settings that can disable their own retrieval.

Main passes the policy-owner address to newly launched apps in the version 4
app-session bootstrap. Already-running workers query that same owner before
each new job, so changing policy does not require an app restart. Main and all
app archives must be rebuilt together to move from session version 3 to 4.
Version/schema refusal happens before decoding the new bootstrap payload;
legacy close messages remain available for standalone callers.

`tests/apppolicy.fpr` covers live read/write/delete/cleanup changes, a concurrent
edit during an in-flight read, preserved unknown opens and held handles, stale
and expired updates, recovery cap changes with retained history, configured
startup/response/close budgets, a caller wait beyond the old 2500 ms limit, and
an unavailable policy owner. It runs through `tools/endpoint-state-check.py`
alongside the existing ownership, app-session, memory and file-policy checks.

Runtime policy validation on 2026-10-20: all six ownership misuse programs were
refused and all ten Portable runs passed (appjobs, appsession, appsessionmemory,
filepolicy and apppolicy, each with one and four workers). Main check-only, the
four check-all verdict unit tests, shell syntax, `git diff --check`, and the
264-pin lock check passed. The compiler executable remained the 2026-10-19
19:39 build (SHA-256
`858ccf88b8b52bad49625629e61fd8c3f9d486b544f60ec2a0a20dea830f199f`).
The sibling checkout advanced from `3206b84` to `d27f825` during this work;
the intervening commits change documentation and Tang Nano/builtin files, not
the compiler or macOS Portable runtime paths used here. Logs are under
`.qos/validation/app-policy-20261020/`.

The Main graphical integration checks also passed with separately built Main
and all six app archives: two boots, app reopen/close, Terminal write/read,
Editor save/build/run/recovery, launch refusals, three viewport sizes, pointer
and focus handling, graphics-owner death, render deadline expiry, and pane
failure/retry. The initial sandbox run stalled in the host graphics-input check;
that check passed with desktop access. The remaining checks resumed using the
already-built artifacts. A missing fault fixture in the resume driver was then
built and the shutdown checks completed separately. This is combined staged
evidence, not a claim that the original sandbox command completed successfully.
Logs and screenshots are under `.qos/validation/app-policy-gui-20261020/`; the
desktop and shutdown summaries are in `app-policy-20261020/`. Physical-board
and native runtime acceptance remain untested.


## Editor launch and hosted-program file access policies

This continuation starts after the app I/O and recovery slice was committed and
pushed as `b9d3b5b`. `editorpolicy.fpr` owns two independently revisioned typed
policies, exposed by a leased namespace adapter:

- `/services/run-policy` and `/services/run-policy/schema`
- `/services/file-access-policy` and `/services/file-access-policy/schema`

Main starts and stops the owner and adapter with its app sessions. Editor gets
the existing namespace address from its app-session context; these services use
the established endpoint text protocol, so the app-session protocol remains v4.
Rebuild Main and Editor to install this slice. Other v4 apps need no wire change.
Policy settings last until Main restarts. A complete update must supply the
current revision; stale, malformed, unauthorized or expired changes leave the
policy and revision unchanged. Changing one policy does not advance the other.
Authorization uses the same cooperative system-process convention as the prior
policy services, not authenticated sender identity.

### RunPolicy

`runpolicy.RunPolicy` is either `RamShare divisor fallbackBytes` or
`FixedBytes bytes`. The default remains a quarter of reported physical memory,
with a 1 GiB fallback when the host cannot report a positive total. All fields
must be positive machine integers. Division rounds down; a zero-byte result
refuses launch. Fixed-byte mode does not depend on the host memory report.

```text
cat /services/run-policy
cat /services/run-policy/schema
write /services/run-policy revision=0 mode=fixed bytes=67108864
write /services/run-policy revision=1 mode=ram-share divisor=8 fallbackBytes=268435456
```

The example assumes an initial revision of zero. Each form requires exactly its
listed fields in that order. Extra or conflicting fields, signed values, numeric
suffixes and overflow are refused. The schema also reports the host memory total,
current revision and next effective byte budget (or an admission refusal).

Editor reads a snapshot after a successful build and immediately before spawn.
The typed `Admission` records that revision and byte budget. The process owner
passes the admitted budget to the existing confinement operation before sending
the child its start message. Editor retains the admission in its model and shows
its revision and exact byte count in the launch output. Subsequent policy edits
never re-confine, kill, or rewrite a running process. This is per-process
confinement, not a reservation of physical memory or a whole-system account.

### FileAccessPolicy and captured grants

`fileaccesspolicy.FileAccessPolicy` carries an allowed directory root, an excluded
directory subtree, maximum path bytes, and read/write flags. Defaults are
`/home/`, `/home/.editor/`, 1024 bytes, and both permissions enabled. Reads and
listings require the read flag; write, append and remove require the write flag.
The policy applies to hosted programs' requests mediated by Editor. It does not
change Editor's own document, build or session-recovery access.

```text
cat /services/file-access-policy
cat /services/file-access-policy/schema
write /services/file-access-policy revision=0 root=/tmp/ exclude=/tmp/private/ maxPathBytes=512 read=1 write=0
```

Every field is required in that order; flags are exactly 0 or 1 and path length
is 1 through the 1024-byte storage wire ceiling. Roots and exclusions are absolute
directory paths ending in `/`, with no whitespace. Request paths may contain
spaces in filenames, but reject control bytes, backslashes, duplicate slashes,
and dot or parent segments. The root itself is not admitted as a file. The
excluded directory itself and its descendants are refused, including listings.

Every new request from an already-running hosted program reads the current
policy and produces a validated `Path` inside a typed `Grant`. A pending job
retains that grant. Already-issued reads and writes complete under their old
admission; edits do not cancel them or undo writes. A listing reply is filtered
using its captured scope and exclusion, so it cannot adopt broader permissions
from a later update. Directory boundaries are respected: listing `/home/a` does
not expose `/home/ab`. Replies for a stopped program are still discarded by the
existing process lifecycle logic.

Both lookups share an introspected 250 ms deadline across namespace open, read,
and lease close. An unavailable configured service refuses the launch or file
request; it never silently restores permissive defaults. Namespace zero is an
explicit standalone mode for isolated models and tests. These policy lookups use
the existing leased adapter, whose expiry and handle limits are still separately
listed follow-up work.

`tests/editorpolicy.fpr` covers codecs, bounds, schema, authorization, independent
revisions, live admission changes, pending reads/listings across revocation, and
service failure. `tests/editorpolicyprocess.fpr` compiles a child through the host
compiler and tests actual confinement before and after a live budget decrease.
`tools/editor-policy-check.py` runs both plus app-session and memory regressions
on one and four workers, and is registered in CI and `check-all.sh`.

Validated on 2026-10-20 with eight successful Portable cases: `editorpolicy`,
`editorpolicyprocess`, `appsession` and `appsessionmemory`, each on one and four
workers. The process test observed the existing child's actual 32 MiB heap
confinement after the policy decreased, then the next child's actual 16 MiB
confinement. The memory regression retained its 3000-operation, 8-root / 2 MiB
bounds. Main check-only, the four check-all verdict unit tests, shell syntax,
Python parsing, `git diff --check`, and the 272-pin lock check passed.

Final focused results are in
`.qos/validation/editor-policy-20261020/access-results.log` and
`process-results.log`, with detailed logs in `access-final/` and `run/`.
The compiler service needed local socket access. Its first process-test attempt
refused an overlong fixture package name; shortening that name to its documented
limit allowed the process checks to run. The compiler executable hash remains
`858ccf88b8b52bad49625629e61fd8c3f9d486b544f60ec2a0a20dea830f199f`,
with sibling checkout `d27f825`. This slice has no new graphical, physical-board
or native-runtime acceptance claim.
