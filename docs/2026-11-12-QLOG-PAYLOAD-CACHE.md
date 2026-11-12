# Qlog v11: cached single-page payloads

Date: 2026-11-12. Kind: change record, measured. Branch `qlog-payload-cache`
on main `0e2cdb9`, FP-RISC pin unchanged (`e138e65`).

## Why

The native replay profiles of 11 November
([replay](evidence/2026-11-11-native-replay-profile.txt),
[entRead](evidence/2026-11-11-native-entread-profile.txt),
[blkRead](evidence/2026-11-12-native-blkread-profile.txt)) showed a replay of
n records reading n pages, each a disk transfer plus a routed block-service
round trip (about 300 ms for 128 records under QEMU). The reason is the
format and the index, not the block path:

- Every record is a header page plus whole payload pages
  (`appendRes`, `np = ceilDiv pl 4096`). An 8-byte event takes two pages, and
  records never share a page.
- The index (`Ent url page pl off len`) kept page numbers only. Every
  `idxReplayE` called `entRead` -> `readPayload` -> `pageRead` for every
  matching record, every time. Nothing cached pages.
- `idxLatestE` read every matching record's payload and kept the last.

## The change

`programs/mods/qlog.fpr`, `qlog v11.0#07c2f7a9d1424b80`:

- `Ent` gains a `Body`: `Uncached` or `Cached String`. An entry whose record
  fits one page (`pl <= pgsz`) keeps its bytes once they are known: from the
  append that wrote them (copied into the storage actor's slab, as the url
  already was) or from the first read. Larger records stay on disk.
- The storage actor's replay (`aReplay` -> `idxReplayF`) returns the same
  bytes and hands the index back with the url's entries filled.
- `idxLatestE` finds the last matching entry first and reads only that one.
- Every read request reads one device page first (the superblock,
  `pageProbe`). A stalled, reset or dead block device therefore fails reads,
  ends the storage actor and latches storage offline exactly as before; the
  `qlogblock` and `qlogowner` legs of `tools/qlog-routing-check.py` check
  this. A first attempt probed with `B.GetBudget`, which Portable's block
  service refuses ("native budgets unsupported"); a second used `B.Status`,
  which never touches the device, so a stalled device went unnoticed by
  cached reads (`qlogowner`'s `stopped`). A replay of n cached records now
  costs this one page read instead of n.

The disk format is unchanged. Memory: the index holds at most the bytes of
single-page records that were appended or read since the actor started,
which is what replaying every url would return anyway. The actor's state
copy at a boundary (`AC.tidied`, adaptive) grows by the same amount.

## Versions

`qlog v11.0` is a major version (the index type changed). `std/fs v6.0`
(`9f0941f56c8b299f`) and `std/lifecycle v7.0` (`80c09fb470067e23`) re-pin it;
nothing else that pins them is a pinned module. `fpr.lock` is regenerated.

The two std modules were recorded by hand: the store blob and the
`versions.db` line, which is what `fpr commit` writes. `fpr commit` compiles
the previous version's store copy for its compatibility check, and a store
copy is held to the non-library safety rules that `std/` files are exempt
from (unsafe signatures), so it refuses `std/fs v5.0` with either compiler.
Their hashes come from the loader's mismatch report (pin `#0000000000000000`
and read "on disk #..."). Fixing `fpr commit` to judge a store copy by its
module's origin is an FP-RISC follow-up.

## Measured

`tests/fsbench.fpr` (new): appends, latest reads and two replays of a
200-record key through `FS.connect` and Files.qa, answers checked. QOS
Portable, M4, one hart, fresh disk, pinned FP-RISC, one run each while a
check-all sweep ran on the same machine:

| Operation | qlog v10 | qlog v11 |
| --- | ---: | ---: |
| Append, one key | 12.7 ms | 12.9 ms |
| Latest, key with 200 records | 69.8 ms | 1.0 ms |
| Latest, alternating one-record keys | 0.96 ms | 0.98 ms |
| Replay of 200 records, first | 69.6 ms | 1.16 ms |
| Replay of 200 records, again | 70.4 ms | 1.16 ms |

The records were appended in the same session, so the first v11 replay is
already cached. A replay after boot reads each single-page record's page
once, then answers from memory.

What is left per read is about 1 ms on Portable whatever the record count:
the probe page read plus the Files/forwarder/storage path. Appends (about
13 ms) are dominated by the durable path (two flushes per v3 append) and
were not changed here; native buffered v2 appends re-read metadata several
times per append (`metaOr` -> `latestSeal` + `legacyMeta`, and `sbW` ->
`ensure` + `metaOr`), which is the next storage item.

## Checks

With the pinned compiler: `tools/qlog-routing-check.py` (block routing, Qlog
route with partial append/restart/service death, Files owner
recovery/no replay/latched offline, system routing, stalled reset, process
storage ABI, both virtio versions, 1 and 2 harts), `tools/portable-durable-check.py`,
`tests/fsbench.fpr`, and `./qos.py test` (smoke) 15/16, the one failure
"files shared" on `net: bind (port busy?)` while another qosp held the port.
Not run: the full check-all sweep, the native QEMU replay benchmark
(`tools/store-wait-bench.py`), the Pi.
