# QOS publication and owned MVU watchers — 2026-10-04

`std/qpublication` is the Files/qlog counterpart of host publication. A system
composition starts one publisher with `P.serve me fs`, shares its handle with
producers, and owns its lifetime. `P.publish me publisher info qaBytes` returns
an immutable archive address or a refusal. `info` is the same name/from/to/version
record carried by `MV.EReload`; hashes are checked compiler root identities.

Publication stores bytes at `apps/live/<name>/<to>.qa`, then appends a complete
catalog snapshot at `sys/reload/publications`. Existing image bytes must match
exactly, and the predecessor must match that module's latest publication.
Duplicate publication writes neither image nor catalog. A failed image write
advertises nothing. A failed catalog write leaves an unpublished image; retry
reuses it and publishes only after a successful catalog write. Actor state
changes only after that write succeeds. On restart the publisher reads the
latest durable snapshot. Only `no such file` means an empty catalog; malformed
catalogs and storage failures refuse startup.

The publisher checks archive structure, LOAD layout, relocation/import sections
and required digest declarations without attaching code. Compiler-provided root
identity, host ABI, cryptographic image/relocation integrity and checked export
compatibility remain authoritative loader gates. This is a trusted producer
surface, not publisher authentication or an independently signed certificate.

## Delivery and ownership

The host and QOS transports share FP-RISC `std/reloadcatalog` for cursor parsing
and typed candidates. `P.poll me fs name cursor` returns candidates and the next
cursor; `P.start` validates the snapshot and returns its current length.
`P.watchFrom fs name cursor` is a starter for:

```
MV.runWatched me cfg app reload (P.watchFrom fs "math" cursor)
```

The runner creates an additional typed event port, starts the watcher, drains it
alongside existing `SEvents` subscriptions, and kills both owned actors after
normal quit (including quit during the initial resize). A startup refusal kills
the new port and returns `Err`. Duplicate event-port subscriptions drain once.
`gameWatched` provides the same ownership for the App/LiveApp facade.

The QOS worker polls every 300 ms, retains its cursor on storage/parse failures,
and sends copied `EReload` records. Publisher and watcher use actor boundaries
to discard per-turn temporaries while preserving state. The publisher explicitly
keeps request bytes before nested Files calls: dropping the received message
root before those receives otherwise invalidates borrowed image fields.

The reload adapter calls `LR.loadPublished me fs env.table info`, which preflights
the loaded identity, resolves an immutable archive from the durable catalog and
uses the existing checked gate. The runner adopts a complete replacement env on
`Ok`; model state survives. Legacy `std/loader` sys/live replay is unchanged.

## Evidence and limits

`tools/publication-check.py` builds real plugin archives and executes two boots
with the same disk, on one and four Portable host harts. It covers image-write,
catalog-write and read failures, malformed catalogs, immutable collisions, stale
predecessors, delimiter injection and invalid archives. It checks exact durable
record counts after retry and duplicate publication, actual worker notification,
MVU state preservation, new code, retained old function values and owned-worker
shutdown. The leg is included in `check-all`.

FP-RISC's `tests/check_owned_watchers.py` covers normal quit, initial-resize quit,
startup refusal and independent event inputs on one/four harts, and is in Base.

The system must provide exactly one publisher per catalog and reserve its image
keys; Files does not enforce a compare-and-swap or per-key immutable capability.
A failed publication acknowledgement is safe to retry through that publisher.
Journal snapshots and polling currently cost O(history); compaction/checkpoints
are future work. Cleanup covers orderly runner exit, not an arbitrary panic or
external kill. Native RV64 publication and power-loss fault injection have not
been executed. No automatic whole-program restart, environment generation,
rejected-version rebasing or image reclamation is added here. Host source watching
still builds host modules; bridging development builds/uploads into this QOS
producer API remains separate tooling work.

The final two-boot publication leg and existing real plugin/type/contract reload
checks passed on one/four Portable harts. FP-RISC full Base passed after the
shared runner changes; full QOS check-all was not rerun for this milestone.
