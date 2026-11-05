# FP-RISC pin trial: 1a09f01 -> 2d3b9d6 (and 15bad00)

Date: 2026-11-03 (finished 2026-11-04). This was a qualification trial, not a release.
The trial ran on `fprisc-pin-trial`. On November 5 its report and evidence were merged into main with the existing compiler pin at `1a09f01`.

## Verdict

Do **not** move the pin to 2d3b9d6 or to 15bad00 as they stand. Each one brings two new failures that reproduce on every run, and both are compiler bugs:

1. **Typed case tests are unsound on values that come from `receive`.** This breaks `pathnotes`. It was introduced by 78000b8 (C1 piece 1), and `FPR_NO_TYPED_CASE=1` avoids it.
2. **`discharge-proven-checks` (Codegen.Interval) does not terminate in practice on guishell's `main`.** This breaks the Main Profile leg. It was introduced by bd45ece (C2 + interval/sharing upgrades), and `FPR_NO_INTERVAL=1` avoids it.

A pin move could ship once both are fixed in fprisc. The alternative is to ship with both rollback flags set, but that gives up the C1 and interval gains.

## Setup

- These are separate worktrees. Main checkouts and `sdk-0.4.0-candidate` were not touched.
  - qos `qos-pintrial` (branch), `qos-pinbase` and `qos-pinbump` (detached at 0bf8bee).
  - fprisc `fprisc-pintrial` (2d3b9d6), `fprisc-pinbase` (1a09f01), `fprisc-pinbump` (15bad00) and `fprisc-pinbisect`.
- Each fprisc worktree was built with `make fpr`. Each sweep was run as `FPRISC_ROOT=<fprisc wt> sh check-all.sh`.
- `check-all.sh` holds a per-user lock, so the three sweeps ran one after another.
- `fprisc.lock.json` is the only file that moves with the pin. `fpr.lock` pins std module content and does not depend on the compiler revision.
- Machine: 10 CPUs and 16 GiB.
  - A VS Code fpr-lang server sat at about 99% CPU during every run.
  - During part of the 2d3b9d6 sweep, a niced build of 15bad00 was running alongside.
  - I reran every new failure on its own afterwards (see "Flaky" below).

## Results

| | 1a09f01 (current pin) | 2d3b9d6 (trial) | 15bad00 (main, +inline bump alloc) |
|---|---|---|---|
| passed | 145 | 141 | 143 |
| failed | 9 | 13 | 11 |
| skipped | 9 | 9 | 9 |

Each sweep has 163 legs. Per-leg results are in `evidence/2026-11-03-fprisc-pin-trial/legs-{1a09f01,2d3b9d6,15bad00}.tsv`.

The table lists only legs that did not pass everywhere. Every other leg passed in all three sweeps.

| leg | 1a09f01 | 2d3b9d6 | 15bad00 | attribution |
|---|---|---|---|---|
| pathnotes: value-space iteration on the Notes app | PASS | **FAIL** | **FAIL** | compiler bug: typed case tests, 78000b8 (below) |
| Main Profile: paged GUI shell (guishell-check) | PASS | **FAIL** | **FAIL** | compiler bug: Interval discharge blowup, bd45ece (below) |
| Files quiesce, block drain and final flush | PASS | FAIL | PASS | flaky under load; passed in isolation at 2d3b9d6 |
| liveboard: std/live end to end | PASS | FAIL | PASS | flaky under load; passed in isolation at 2d3b9d6 |
| Editor and Terminal live preferences | FAIL | FAIL | FAIL | already failing (known) |
| Graphics.qa | FAIL | FAIL | FAIL | already failing (known timeout) |
| Native instruction ratchet | FAIL | FAIL | FAIL | already failing (known) |
| dedup ratchet | FAIL | FAIL | FAIL | already failing (known Sol/Infer) |
| sol Ok/Err tier + txn hygiene | FAIL | FAIL | FAIL | already failing (known) |
| Sol NN | FAIL | FAIL | FAIL | already failing (known Vec/Sol NN) |
| Vec fusion | FAIL | FAIL | FAIL | already failing (known Vec/Sol NN) |
| Vec fixpoint + write-back fold | FAIL | FAIL | FAIL | already failing (known Vec/Sol NN) |
| the tree as a toolchain (qos.py install) | FAIL | FAIL | FAIL | already failing; not on the known list. It prints only "install done", so it may be specific to worktrees. I did not investigate. |
| 9 GL/Xvfb/aarch64/FPRLive/POS legs | SKIP | SKIP | SKIP | missing host tools, the same in every column |

Buildroot service supervision passed in all three sweeps. No failure is attributed to the layout table, list fusion, case-known, tuple scalars, tick batching, pair returns, TRMC or inline bump allocation (15bad00).

## 1. pathnotes: typed case tests trust a type that `receive` cannot promise

**Symptom.** The Notes app's message port logs `send: target is not an actor` and then `mvu: message port: dead actor`.

**Flag bisect.** Of the eight `FPR_NO_*` flags, only `FPR_NO_TYPED_CASE=1` makes the leg pass. I also cross-built with the flag on and off:

- Building the plugins either way is fine.
- Building the app is what triggers the bug.

**Cause.** 78000b8 (docs/2026-11-02-TYPED-CASE.md) lowers `CTagEq` on a static nominal type to `OVariantTest`, which reads only the variant word at +4. The value is assumed to have the static type, but a value from `receive` has no such guarantee.

std/mvu `portStep` (std/mvu.fpr, lines ~173-189) cases on `PortQ = PDrain from | PBarrier from | _`. The pathnotes driver sends `("note", "hello qos")` tuples. A tuple's variant word is 0, which matches `PDrain`, so the port sends a reply to the string pointer.

**Minimal repro.** The file is `evidence/.../typedcase_receive.fpr`:

```
Q = Type (PA Int | PB Int).
main =
  me = myself 0;
  _ = send me ("x", "y");
  m = receive me;
  r = case m of
      PA x -> "PA (wrong: a tuple matched a constructor)"
    | PB x -> "PB (wrong)"
    | _ -> "other (right)";
  print r.
```

Build it with `FPR_HOME=$F $F/fpr build typedcase_receive.fpr -o tc && ./tc`. Results:

| build | output |
|---|---|
| 2d3b9d6 | `PA (wrong...)` |
| 15bad00 | `PA (wrong...)` |
| 2d3b9d6 or 15bad00 with `FPR_NO_TYPED_CASE=1` | `other (right)` |
| 1a09f01 | `other (right)` |

**Fix direction (for fprisc, not done here).** Possible fixes:

- Treat a scrutinee whose provenance is `receive` (or any untyped source) as dynamic, so it gets the full tid + variant test.
- Or make `receive` results carry no static nominal type.

Nothing on the QOS side can fix this cleanly, because the code is in fprisc std/mvu.

## 2. Main Profile: Interval discharge does not finish on guishell `main`

**Symptom.** `guishell-check` times out at 240 s inside `make qos-app PROG=tests/guishell.fpr`.

| build | time for that unit |
|---|---|
| 1a09f01 | about 50 s |
| 2d3b9d6 | still running at 1500 s when killed |
| 15bad00 | also times out |

**Flag bisect.**

- No single flag fixed it (each run killed at 240 s).
- Turning all eight off did not fix it either.

**Commit bisect** on unit build time:

| commit | result |
|---|---|
| 8f90b76 | good, 49 s |
| ccb735b | good |
| f05f089 | good |
| 830fd11 | good, 50 s |
| cf59f43 | bad |
| 392edc7 | bad |
| bd45ece | bad |

The first bad commit is **bd45ece**, "Type specialization on builtin (C2) and interval/sharing upgrades". `FPR_NO_INTERVAL=1` fixes it: 49 s, 48 s and 48 s over 3 of 3 runs. That flag gates both `discharge-proven-checks` and `share-pure-across-blocks`.

**Where it hangs.** I traced the pass with a temporary Debug.Trace build. That patch has since been reverted. Guishell's `main` enters `discharge-proven-checks` (Codegen.Interval.discharge) and never leaves it. The function's shape:

- 195 blocks; 785 instructions before the pass, 689 after
- 78 conditional branches and 105 calls
- mostly acyclic diamonds

My hypothesis is that bd45ece's new fact intersection at acyclic joins, or its transitive `diffUB`, is superlinear in this shape. Synthetic programs did not reproduce it: I tried nested cases and sequential joins. The repro is therefore `tests/guishell.fpr` at qos 0bf8bee, together with the IR of `main` captured entering discharge (`evidence/.../guishell-main-before-discharge.ir`). The bisect log is `evidence/.../bisect-guishell-compile.txt`.

**Open oddity.**

- `FPR_NO_INTERVAL=1 FPR_NO_TYPE_SPEC=1` stalled in 3 of 4 runs and finished once, in 47 s.
- `FPR_NO_TYPE_SPEC=1` alone also stalls.

I cannot explain this. Either TYPE_SPEC changes what reaches another quadratic path, or the timing is noisy under the background CPU load. It is worth a look once the discharge fix lands.

## Flaky (not attributed)

- **Files quiesce.** At 2d3b9d6 in the sweep, it failed with `storage service: deadline exceeded` under QEMU with 2 harts while the machine was heavily loaded. Run alone, it passed in 85.9 s. It passed in the 15bad00 sweep.
- **liveboard.** At 2d3b9d6 in the sweep, it failed with `ConnHost failure ... errno=61` (connection refused). Run alone, it passed, and it passed in the 15bad00 sweep.
  - Memory, worth keeping an eye on (one sample each):

    | build | 100 sessions resident | per session | heap |
    |---|---|---|---|
    | 2d3b9d6 | 2402 MiB | 24122 KiB | 2745 MiB |
    | 1a09f01 | 2071 MiB | 20791 KiB | 4465 MiB |

## Before a real pin move

1. Fix the typed-case soundness bug in fprisc and add the repro above as a test.
2. Fix the discharge blowup and add guishell `main`, or a reduction of it, to the compile budget gate.
3. Rerun this sweep. Then check the three legs that are failing at every pin: the known ratchets, Sol NN/Vec and the toolchain leg.
