# FP-RISC pin trial: 1a09f01 -> 43f02dc (codegen 204)

Date: 2026-11-05. This is a qualification trial, not a release. It reruns the method in
[2026-11-03-FPRISC-PIN-TRIAL.md](2026-11-03-FPRISC-PIN-TRIAL.md) ("Before a real pin move")
against fprisc main 43f02dc. `fprisc.lock.json` is unchanged on this branch.

## Verdict

**No-go.** Do not move `fprisc.lock.json` to 43f02dc yet.

- The two compiler bugs from the 3 Nov trial are fixed. pathnotes and the Main Profile
  (guishell) both pass at 43f02dc.
- **One new failure reproduces:** `tests/qsysfail.fpr` check 12 at 4 harts. A files manager
  traps in `Storage.spawnOn` because `Sys.spawnInbox` refuses admission after 64 holders have
  died, even though `Sys.alive` already reports those holders' file actors as dead. Two legs
  show it: "Storage deadlines..." and "qsys failure paths...".
  - It came in with the coordinated compact-runtime pair: fprisc a7f4fd6 and QOS 6a273c6.
  - No `FPR_NO_*` flag and no `FPR_COMPACT_CELLS=0` avoids it. That puts it in the runtime or
    the QOS integration, not in an optimization pass.
- Everything else matches the baseline, apart from one improvement and one load flake (below).

Two QOS-side findings matter for the pin decision, and neither is a compiler issue:

1. **QOS main no longer builds with its own lock.** Since 6a273c6 (compact runtime ABI), QOS
   calls `fpr_alloc_raw`, `fpr_free_raw` and `fpr_slab_start`. fprisc 1a09f01 does not have
   them, so main + 1a09f01 fails every leg that builds a QOS app. Only a compiler at or after
   a7f4fd6 can build main. Main and its lock disagree either way until the pin moves.
2. **QOS main (aac3edc) does not compile `programs/system.fpr` with either compiler.** The
   merge of ba8b176 ("epservice: explicit receive drops and unsafe signatures", whose own
   message says it was never tested) leaves 7 safety-line refusals: rule 2 of the
   safe/unsafe line, callers of unsafe-marked functions without `unsafe` signatures. See
   `evidence/.../aac3edc-system-safety-refusal.txt`.
   - 19e15cf, the commit before that merge, compiles cleanly. 1a09f01 and 43f02dc give the
     same 7 errors on aac3edc.
   - This is what broke "Qlog and bootstrap block routing" in the first (aborted) trial sweep.
   - It must be fixed or reverted on QOS main before any pin move. This record does not
     change it.

What a pin move needs:

1. A fprisc fix for the dead-actor admission failure, with qsysfail check 12 at 4 harts (or
   a reduction) as its test.
2. A fixed or reverted aac3edc on QOS main.
3. A rerun of this sweep on that QOS commit.

## Setup

- Worktrees, all removed afterwards. Main checkouts and `sdk-0.4.0-candidate` were not
  touched.
  - qos `qos-pt43`: this branch, `fprisc-pin-trial-43f02dc`, from main aac3edc. It holds
    only this record.
  - qos `qos-ptbisect`: the trial sweep at 19e15cf, plus the QOS bisect.
  - qos `qos-ptbase`: the baseline at 0bf8bee.
  - fprisc `fprisc-pt43` (43f02dc), `fprisc-ptbase` (1a09f01) and `fprisc-ptbisect`
    (a7f4fd6, then 7b24f9c).
- Each fprisc worktree was built with `make fpr`, about 4 minutes. Each sweep was run as
  `FPRISC_ROOT=<fprisc wt> sh check-all.sh`. check-all exports `FPR_HOME=<qos>`,
  `FPR_PATH=<fprisc>` and `FPR_FOREIGN=<qos>/core/foreign.fpr` itself. Spot checks set them
  explicitly.
- **Pairings.** QOS main cannot be paired with 1a09f01 (finding 1) and does not build its
  system at aac3edc (finding 2). The comparison is therefore:
  - baseline: **qos 0bf8bee + fprisc 1a09f01**, the same pairing as the 3 Nov baseline.
  - trial: **qos 19e15cf + fprisc 43f02dc**. 19e15cf is main minus the untested epservice
    merge. From 0bf8bee to 19e15cf, QOS changes only by the compact-ABI adaptation
    (6a273c6), the Pi soak hardening (54bc875) and docs/evidence.
  - Both trees have the same 163 legs, by name.
- The first trial sweep, against aac3edc, was stopped after 42 legs
  (`legs-43f02dc-qosaac3edc-partial.tsv`, 2 failures: Qlog routing from finding 2, and the
  known native ratchet).
- Machine: 10 CPUs and 16 GiB. The two sweeps ran one after another (check-all's lock). The
  spot checks below ran during the sweeps, so they share the sweeps' load.

## Results

| | 1a09f01 / qos 0bf8bee (3 Nov) | 1a09f01 / qos 0bf8bee (today) | 43f02dc / qos 19e15cf |
|---|---|---|---|
| passed | 145 | 145 | 143 |
| failed | 9 | 9 | 11 |
| skipped | 9 | 9 | 9 |

Per-leg results are in `evidence/2026-11-05-fprisc-pin-trial-43f02dc/`:
`legs-1a09f01-qos0bf8bee.tsv`, `legs-43f02dc-qos19e15cf.tsv`, and `legs-not-green.tsv` for
the three-way view. They were produced with `legs.py` and `compare.py`, which sit beside them.

| leg | 3 Nov base | base | trial | attribution |
|---|---|---|---|---|
| Storage deadlines, late replies and finite service budgets | PASS | PASS | **FAIL** | new: dead-actor admission at 4 harts (below) |
| qsys failure paths (tests/qsysfail.fpr) | PASS | PASS | **FAIL** | the same bug: qsysfail check 12 |
| liveboard: std/live end to end | PASS | PASS | FAIL | flaky under load: passed 2/2 alone at 43f02dc (same as 3 Nov) |
| Editor and Terminal live preferences | FAIL | FAIL | **PASS** | improvement at 43f02dc |
| Native instruction ratchet | FAIL | FAIL | FAIL | known. The selected system.fpr segment grew from **398 to 474** instructions (ceiling 312); runtime call sites stayed at 95 (ceiling 67) |
| dedup ratchet | FAIL | FAIL | FAIL | known. Sol/Infer.hs grew from 153 to 158 lines (ceiling 132) |
| Sol NN, Vec fusion, Vec fixpoint | FAIL | FAIL | FAIL | known; identical output at both pins |
| sol Ok/Err tier + txn hygiene | FAIL | FAIL | FAIL | known; `check-all.sh: line 274: K: unbound variable` at both pins, which is a check-all bug, not a compiler one |
| the tree as a toolchain | FAIL | FAIL | FAIL | known; identical ("install done", then the leg fails) |
| Graphics.qa | FAIL | FAIL | FAIL | known; the `gfxapps.fpr` build times out at both pins |
| 9 GL/Xvfb/aarch64/FPRLive/POS legs | SKIP | SKIP | SKIP | missing host tools |

pathnotes and Main Profile (guishell-check) pass at 43f02dc. 7b24f9c's fixes hold in the full
sweep.

## The new failure: qsysfail check 12, dead holders keep spawn admission

**Symptom.** Check 12 does the following:

1. Spawns 64 clients. Each opens a file under one files manager and ends without Close.
2. Waits 20 ms.
3. Opens a 65th file.

At 43f02dc, at 4 harts, the 65th open returns `/tmp/z65: its owner dead actor`. The
namespace forwarded to the files manager, and the manager had died. The manager's death is
logged as:

```
[ERR] actor failed: storage actor admission: <9005.0>
```

Code path: `filesSpawn` (programs/mods/qsys.fpr) calls `Wire.spawn`, which is std/storage
`spawnOn`. `spawnOn` calls `Sys.spawnInbox` and traps on `Err`.

`filesSpawn` only gets that far after its own `filesLive` count, which uses `Sys.alive`, says
fewer than 64 file actors are live. So the runtime's admission refuses while the dead
actors already read as dead. At 1 hart the check passes.

**Second defect.** The refusal reason prints as `<9005.0>` (in 3 runs, `<9005.1>`). 9005 is
`T_ACTOR` in 43f02dc's runtime/fpr.h. So the `Err` payload is an actor object, not one of
the runtime's denial strings (`heap_denied`, "fixed heap: admission denied"). Either the
returned Result is malformed, or the refusal does not come from the path that builds those
strings.

**Reproduction.** `evidence/.../qsysfail-runner.sh <qos tree> <fprisc root> <tag> [runs]
[VAR=val...]` builds the portable host (`-DQOS_BLK_TEST`) and `tests/qsysfail.qa`, then runs
it at `FPR_HARTS=4`. About 50 s per configuration. A failing run is in
`qsysfail-43f02dc-fail.log`.

**Results** (`qsysfail-matrix.tsv`; "trapped" = the manager died as above):

| qos | fprisc | env | pass | trapped |
|---|---|---|---|---|
| 0bf8bee | 1a09f01 | - | 7/7 | 0/7 |
| 0bf8bee | 7b24f9c | - | 5/5 | 0/5 |
| 19e15cf | a7f4fd6 | - | 0/2 | 2/2 |
| 19e15cf | 43f02dc | - | 1/6 (and 0/4 more: the two sweep legs and two service-group reruns) | 5/6 |
| 19e15cf | 43f02dc | `FPR_COMPACT_CELLS=0` | 0/2 | 2/2 |
| 19e15cf | 43f02dc | 13 flags of the second half (TRMC..INLINE) off | 0/2 | 2/2 |
| 19e15cf | 43f02dc | TYPED_CASE..SCALAR_WORKERS off | 0/2 | 2/2 |
| 19e15cf | 43f02dc | INDEXED_MEMORY..TYPE_SPEC off | 1/6 | 5/6 |
| 19e15cf | 43f02dc | each of those 7 flags alone | 0-2/4 each | 2-4/4 |
| 19e15cf | 43f02dc | check 12 waits 500 ms instead of 20 ms | 1/4 | 3/4 |
| 19e15cf | 43f02dc | `FPR_LAYOUT_CHECK=1` | 1/3 | 2/3, no layout fault reported |
| 19e15cf | 43f02dc | `FPR_BUMP_CHECK=1` | 0/3 | 3/3, bump check clean |

Across all runs, the manager trap and a failed check 12 coincide exactly: 47 of 47 failing
runs trapped, and 0 of 23 passing runs did.

**Attribution.**

- The bug is not present at 7b24f9c with qos 0bf8bee (5/5), and it is present at a7f4fd6
  with qos 19e15cf.
- a7f4fd6 is the first fprisc commit with the compact runtime ABI, and 6a273c6 is QOS's
  adaptation to it. Neither builds against the other's predecessor, so the bisect cannot
  split them further.
- No codegen rollback flag removes the failure, and neither does the legacy cell layout.
  Several single flags shift the pass rate a little, which is consistent with a race and not
  with a miscompile.
- Waiting 25 times longer does not help. So this is not slow reclamation: some per-actor
  admission resource of a dead actor is not returned, or is miscounted, on multi-hart runs.
- The suspects are in fprisc runtime/actors.c and the a7f4fd6 runtime changes: the
  admission charges in `a_spawn_inbox` (stack block, buckets, channels, inbox charges, acb)
  and their release on actor death. A QOS-side cause from 6a273c6 (constructor registration
  before actors start, raw storage buffers) is not ruled out.
- Diagnosis only. Nothing was changed in fprisc.

## Other observations

- With all 26 `FPR_NO_*` flags set, and even with 13 of them, the build fails: the unit-cache
  name passes the 255-byte filename limit (`openTempFile: invalid argument (File name too
  long)`, and then the clang `.o`). The cache key spells every flag suffix into one path
  component. It is a small fprisc bug, worth hashing the suffix.
- liveboard-check with an empty `XDG_CACHE_HOME` times out at the "Hash" command at both
  pins, which looks like a cold-cache build outlasting the client's 20 s socket timeout.
  With the normal cache it passes at both. This is a harness quirk, not a regression.
- The native ratchet's segment growth (398 to 474) is not a new failure, because the leg
  fails at both pins. It is the largest size change in the sweep, and it is worth a look
  when the ceiling is next revisited.
