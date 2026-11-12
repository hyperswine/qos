# Archived branches landed on main (2026-11-12)

Kind: landing note, tested on the hosted arm64 Mac only.

The branch cleanup earlier today left work that was not on main under
`archive/2026-11-12/*` tags. This note records what was applied to main from
them, what had to change to fit main as it is now, and what was checked. The
tags are deleted after this lands. FP-RISC's half is
`fprisc/docs/2026-11-12-ARCHIVED-BRANCHES-LANDED.md`.

## What landed

| Archive | Applied as | Notes |
|---|---|---|
| `held-fs-endpoints` | merge of the linear endpoints (`mods/epclient` v1.0 and v2.0) and the hot service sites note | the std/fs forwarder experiment is kept only as `docs/evidence/2026-11-12-held-fs-forwarder.patch`: it measured no gain |
| `fprisc-pin-rt` | `-ffixed-x27` on every RISC-V C compile, the arcaudit edit, the pin trial note | the pin itself moves further, see below |
| `qlog-payload-cache` | ported onto main's Qlog as v22 | main's Qlog had moved (v21), so this is a port, not a cherry-pick |

The FP-RISC pin is now `94efae2b`, FP-RISC main with every archived FP-RISC
branch on it (receive-loop form for QOS app images, direct handoff, inline
small messages, linear record update; `codegenRev` 219).

## What had to change

- **Version cascade.** Qlog v22.0 (`045dbfa936f832eb`) changes std/fs
  (v6.0 `19932fc6492e8a87`) and std/lifecycle (v7.0 `2ec580ebc636437d`);
  their consumers are repinned and `fpr.lock` rewritten (336 pins).
- **epclient pins.** Twelve programs and tests, and `tools/guishell-check.py`,
  pinned epclient v1.0 while the working module is v2.0 (a superset: it adds
  `openUntil`, `readUntil`, `writeUntil`, `closeUntil`). A pin that is not the
  working module resolves from `.fpr/store`, and store copies, with what they
  import, are held to the strict rules for non-library modules. With the new
  compiler that refused `read` in the stored `ep` (`unsafe ... but has no
  explicit signature`) and qsys did not build. All are repinned to v2.0
  `e09b467f350a5396`. The general rule: a stale pin is not only old code, it
  is code checked under different rules.
- **Two stale checks, both stale on main since `81bb25c`.** The Editor now
  writes its recovery copy as `SaveRecovery` with the `qed2` record:
  `tests/appsession.fpr` expected the old `Put` of a `qed1` record, and the
  `qed2` restore path did not print `editor: recovered <path>`, which the Main
  Profile shell check waits for. The test now expects the new record, and the
  guarded restore prints the same line the `qed1` path prints.

## Checked

`check-all.sh` at the new pin, before the fixes above: 137 passed, 17 failed,
9 skipped, against 145 / 9 / 9 at the last pin trial. The eight extra
failures:

| Legs | Cause | Now |
|---|---|---|
| qsys two boots | the epclient store resolution above | passes |
| endpoint state, hosted timers, editor policy, editor state, preferences | the stale `appsession` expectation | all 16 service checks pass |
| Main Profile | the missing `editor: recovered` line | passes |
| native instruction ratchet | segment 490 > 474 (`spawnUarts`), call sites 173 > 95 (`aServe@qlog`) | **still red** |

The ratchet overage is main's own: unmodified main `73fb643` with the same
compiler measures 490 / 180. The ceilings (474 / 95) were set on purpose and
are not raised here; that needs a decision.

Rerun after the fixes, one at a time rather than a second full sweep: the 16
service checks, qsys two boots, the Main Profile shell check, `appsession`,
`epecho`, `epbench`, `epproc` (as `tools/epproc-check.sh`), `kbdread`,
`gfxshare`, `filessvc`, and `qos.py lock --check`.

fsbench replay with the Qlog cache on this tree: 1.17 and 1.31 ms.

The nine standing failures from the pin trial are unchanged: failure honesty,
liveboard, the dedup ratchet, Graphics.qa with the real Terra II and dungeon,
toolchain, Sol NN, Vec fusion, Vec fixpoint, sol Ok/Err.

## Not checked

No second full sweep after the fixes. The Pi 4B, the RISC-V boards, Linux A64
and a native x86-64 host were not run. Stale pins that were already on main
and are not part of this work are left as they were: std/actor (frozen on
purpose), coreutil, mods/files in `tests/storagedeadlines`, mods/timer in
sysep, std/block, std/blockio, std/net, std/storage.
