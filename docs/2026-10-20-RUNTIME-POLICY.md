# Runtime policy and explicit state types

Kind: implementation record and staged design plan. Applies to the working tree
based on QOS `94d1b81`, with the file reclamation and check-all fixes recorded in
[design alignment](2026-10-18-QOS-DESIGN-ALIGNMENT.md). Started 2026-10-20.

QOS policy should be ordinary typed FP-RISC state owned by a live service. A user
should be able to discover its effective values, constraints, usage and revision,
then change it without rebuilding or restarting the system wherever the resource
contract permits. Moving literals into a constants file alone does not achieve
this. The first implemented slice is the file manager policy below; the remaining
rows are work to do.

## Work queue

| Current source and behavior | Proposed type | Runtime change boundary | Status |
|---|---|---|---|
| `programs/mods/qsys.fpr`: 64 live file actors, 1024-byte new paths, 2000 ms reclamation, 1000 ms retirement margin | `FilesPolicy` (module `filepolicy`, constructor `Policy`) | Atomic manager update; next admission or retirement request, including existing actors | Implemented in this working tree |
| `programs/mods/appjobs.fpr`: read 500 ms, write 2000 ms, delete 1000 ms, cleanup 150 ms; `programs/mods/appclient.fpr` recovery cap of 3 attempts | `AppIoPolicy`, `RecoveryPolicy` | Snapshot at operation/recovery start; keep original in-flight deadline and cleanup obligation | Planned |
| `programs/mods/editapp.fpr`: child memory = physical RAM / 4, fallback 1 GiB | `RunPolicy` | New launches first; changing a running process requires resource-account support and cannot revoke outstanding allocations silently | Planned |
| `programs/mods/editapp.fpr`: `/home/` access, `.editor/` exclusion and path checks | `FileAccessPolicy`, validated path type | Revalidate new requests after a policy update; define explicit revocation semantics for already-issued capabilities | Planned |
| `programs/mods/appjobs.fpr`: `{held=(0,0), uncertain=""}` | Owned endpoint state, e.g. `Vacant`, `Held`, `Uncertain` | Explicit transitions preserving handle ownership and uncertain outcomes; inspect state, never overwrite it with arbitrary settings | Planned next |
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
