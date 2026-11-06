# Revert of the untested epservice WIP (ba8b176)

Date: 2026-11-06. Kind: repair of main. Found by the 5 Nov pin trial
(`docs/2026-11-05-FPRISC-PIN-TRIAL-43F02DC.md` on branch `fprisc-pin-trial-43f02dc`,
finding 2): main aac3edc does not compile `programs/system.fpr` with fprisc 1a09f01
or 43f02dc. `fprisc.lock.json` is unchanged.

## Decision

**Reverted ba8b176.** `programs/mods/epservice.fpr` is again byte-identical to 19e15cf
and to its pinned store version `epservice v3.0 e8bce05a1ddf73db`.

## Why it broke the build

ba8b176 edited only `programs/mods/epservice.fpr`. Nothing uses that file unpinned:
all 23 users pin `epservice#e8bce05a1ddf73db`. The break came from two rules working
together:

1. **Pinned use with drifted source** (fprisc `compiler/Modules.hs`, `loadDeps`). A
   pinned `use` whose source file no longer hashes to the pin resolves from
   `.fpr/store/<hash>.fpr` instead.
2. **Trust is by path** (fprisc `compiler/Safety.hs`, `trustedLibraryPaths`, and QOS
   `core/trusted-modules.txt`). The manifest lists `../programs/mods/epservice.fpr`
   ("Reviewed Files endpoint lease owner..."), but not `.fpr/store/e8bce05a1ddf73db.fpr`.
   The only epservice store entry it lists is the prior v2.0 `878fb2196060eb47`.

So after the edit, every build loaded the same v3.0 content from an untrusted path. Two
safety-line refusals followed:

- the store copy's own recursive helpers without `unsafe` signatures (`liveLeases`,
  `leaseCount`, `findLease`, `removeLease`);
- callers that reach its unsafe-marked functions through it (`read` in
  `programs/mods/appsep.fpr`, and `getc` and `epOf` in `programs/system.fpr`).

Those are the 7 errors. The code is the same as before. Only the trust it was loaded
under changed.

## Why not finish the change instead

Finishing it would mean minting the edited module as a new epservice version and
moving its 23 pins. The minting is the blocker. fprisc's stage-1 note
(`fprisc/docs/2026-10-24-REGIONS-STAGE1.md`, "QOS preferences leg") records that
`fpr commit` refuses this exact module. Its frozen dependencies
`std/actor#201a0e9bf98a5154` and `ep#c66ad65e68dd97f5` lack explicit `unsafe`
signatures under today's rules (17 and 14 functions). The unmodified module fails the
same way. Finishing therefore means:

- re-freezing `std/actor` and `ep` first, with their roughly 300 `fpr.lock` lines;
- adding new store entries to `core/trusted-modules.txt`, which needs review.

That is a publication-workflow change, not a repair to main. The WIP also never ran.

## What the WIP was for, still open

- Since fprisc regions stage 1 (2026-10-24), the compiler no longer inserts `drop`
  after a receive. epservice's `A.tidy` hand loops (`nsReceive`, `lsReceive`,
  `sReceive`) now hold each request root until the next `poolReset`. That is bounded
  by the tidy cadence, so it is not a leak. It does exceed the 8-root allowance in
  `tests/preferences.fpr`.
- The WIP added `_ = drop m` to those three loops, plus `unsafe` signatures on
  `lsRead`, the `untilStep` family and the lease helpers. That diff is commit ba8b176,
  so it can be recovered with `git show ba8b176`.
- Landing it later needs, in order:
  1. re-frozen `std/actor` and `ep` pins that the safety line accepts;
  2. `fpr commit` of epservice;
  3. a trusted-modules entry for the new store hash (or moving the trust to the hash);
  4. `qos.py lock`.

The preferences leg stays the stage-1 open item until then.

## Verification

Results (fprisc 43f02dc, built in its own worktree):

| tree | `make -C qos native` (system.fpr) | `tools/check-services.py --only qlog-routing` |
|---|---|---|
| this branch (revert) | builds; epservice loads from its trusted source | ok (182.8 s) |
| same tree with aac3edc's `epservice.fpr` restored | fails: the same 7 refusals; log shows `epservice#e8bce05a... resolved from .fpr store` | not run |

Environment: `FPRISC_ROOT=FPR_PATH=<fprisc 43f02dc>`, `FPR_HOME=<qos>`,
`FPR_FOREIGN=<qos>/core/foreign.fpr`. `SYSTEM` defaults to `programs/system.fpr`.
`make -C qos native SYSTEM=programs/system.fpr` from the repository root resolves the
path from `qos/` and finds no file, so pass no `SYSTEM`, or pass `SYSTEM=../programs/system.fpr`.

The full check-all sweep was not rerun here. Item 3 of the 5 Nov trial's "What a pin
move needs" (a rerun on a fixed QOS commit) is still to do, after the fprisc
dead-actor admission fix.
