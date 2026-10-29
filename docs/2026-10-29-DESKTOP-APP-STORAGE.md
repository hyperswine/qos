# Desktop app storage, SDK v2

Date: 2026-10-29. Implements slice 3 of the
[Portable workflow](2026-10-28-PORTABLE-APP-WORKFLOW.md), following the
[disk/install milestone](2026-10-29-DESKTOP-DISK-INSTALL.md).

## App API

Import `D = use "qos/desktop"`. Return commands from `init` or `update`:

| Command | Successful `D.Arrived token` value |
|---|---|
| `D.Fetch token (D.Read key)` | `Ok D.Missing` or `Ok (D.Value text)` |
| `D.Fetch token (D.Write key text)` | `Ok D.Saved` |
| `D.Fetch token (D.Remove key)` | `Ok D.Removed` |

An empty stored string is `Value ""`, distinct from `Missing`. Removing an
absent key is acknowledged. All operations can return `Err why`, including
no disk, invalid identity/key, admission failure, full disk and timeout.
The existing asynchronous `Clock` effect is unchanged.

Main supplies the installed archive's validated stable manifest ID at session
bootstrap. Jobs carry a key, never an ID. A record is stored under
`app-data/<id>/<hex key bytes>` in Main's existing single disk-owner service.
The ID excludes the app version, project directory, source and archive filename.
Replacing an archive by ID leaves these records intact. Different IDs have
different namespaces even when they load the same compiled module table.
Legacy unbound session launch helpers remain usable but refuse store jobs.

Keys are nonempty strings. Derived keys must fit the existing 1024-byte storage
key budget; hex encoding uses two bytes per key byte after the identity prefix.
Values use the existing 4 MiB storage payload admission limit. No directory,
listing, multi-key transaction, or new storage manager is introduced. These are
cooperative native plugins sharing Main's runtime: identity namespacing does
not provide memory protection or a security boundary against hostile code.

## Acknowledgements and close

`Saved` and `Removed` follow the existing storage owner's durable commit
acknowledgement, with its flush and failure semantics. `Missing` is returned
only for the owner's explicit missing-record error, never for a timeout or a
missing disk. A mutation timeout retains the existing **outcome unknown**
message: the write may have committed. The SDK does not replay it. Read back
explicitly and decide what to do; a new write is a new mutation.

The scaffold counter reads on open, updates its visible committed count after
`Saved`, and offers `R` to read/reconcile. A malformed saved value is shown as
an error rather than overwritten. Backspace explicitly resets it. The existing
ordered app worker drains earlier jobs before acknowledging normal close;
a forced close or timeout still reports uncertainty rather than promising a save.

## Compatibility

The public API is `qos.desktop/2`, with bootstrap `qos.app-session/5`.
Hosts retain Portable ABI `22.137`; Main, appwire, public SDK and generated
adapters must be a matching set. The installer refuses old API/session
archives. Session negotiation checks the version before decoding the expanded
bootstrap payload. Rebuild session-4 prototype apps against v2 and use a
matching Main profile. Automatic migration of arbitrary older disks/profiles
is not implemented; never replace a real user disk with a newly seeded disk
as an upgrade strategy. Release-package upgrade acceptance is the next slice.

## Validation

On macOS AArch64, `tests/appstore.fpr` checks ID/key admission, byte escaping,
missing versus empty, read/write/remove acknowledgements, identity separation,
unbound refusal and uncertain writes without replay, with 1 and 4 workers.
`tools/preferences-check.py` includes that fixture and existing session,
preferences and editor regressions.

`tools/portable-sdk-check.py` builds a persistent external counter against a
read-only installed SDK while denying QOS/FP-RISC checkout access and excluding
GHC, Cabal and make. Its prebuilt driver checks close/reopen, host restart,
app replacement, the same code under a second ID, and close immediately after
queuing a save. Graphical Main then loads the saved count and increments it;
offline inspection verifies the committed value and unrelated records.

The [recorded evidence](evidence/2026-10-29-desktop-app-storage.json) identifies
binaries, profile hashes and source dirty flags. It is local macOS evidence,
not a claim about other architectures, CI, a published package or physical
power-loss qualification. This milestone reuses existing disk persistence;
it adds no garbage collector.

One existing check remains red: the live `preferences` endpoint-retention
assertion permits at most eight extra ARC roots after 500 changes. The same
instrumented workload at the preceding `a6af199` commit and this change both
report roots `55/71/87` and occupied bytes `11520/11776/11776` across two
500-change batches. This is a reproduced pre-existing failure, not a passing
memory-retention qualification. Its threshold is unchanged; investigating the
root accounting is separate from this storage contract.
