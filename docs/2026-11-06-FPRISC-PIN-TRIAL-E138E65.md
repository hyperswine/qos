# FP-RISC pin trial: 1a09f01 -> e138e65 (codegen 204)

Date: 2026-11-06. This reruns the 5 Nov trial
([2026-11-05-FPRISC-PIN-TRIAL-43F02DC.md](2026-11-05-FPRISC-PIN-TRIAL-43F02DC.md), carried
onto this branch) after both of its blockers were fixed and merged. It is a qualification
trial, not a release. `fprisc.lock.json` is unchanged on this branch.

## Verdict

**Go.** fprisc e138e65 can replace 1a09f01 in `fprisc.lock.json`. Moving the pin, and SDK
0.4.0, remain separate decisions; this record does not make them.

- The full check-all sweep at qos 03ccd4a + fprisc e138e65 has **no new failures** against
  the baseline (qos 0bf8bee + 1a09f01): 146 passed, 8 failed, 9 skipped, against 145/9/9.
- Every one of the 8 failures fails the same way at both pins (the known list below).
- The one difference is an improvement: "Editor and Terminal live preferences" fails at
  the baseline and passes here, as it did at 43f02dc.
- Both 5 Nov blockers are gone:
  - **qsysfail check 12 at 4 harts** passes. Both legs that showed it ("Storage deadlines..."
    and "qsys failure paths...") pass in the sweep. A repeat of `tests/qsysfail.fpr` at
    4 harts passed **10/10** with no `storage actor admission` trap; at 43f02dc it failed
    about 80% of runs.
  - **`programs/system.fpr`** compiles again: "Qlog and bootstrap block routing" (the
    qlog-routing service leg, which builds the system image) passes.

## What changed since 5 Nov

- **fprisc main e138e65** = 912313d plus a merge of `fix-spawn-result-free` (5421687, record
  in fprisc `docs/2026-11-06-QOSAPP-A64-FP-CONTEXT.md`). The qsysfail failure was not an
  admission refusal, which corrects the 5 Nov diagnosis. A QOS app's AArch64 context switch
  saved only integer registers. clang kept `a_spawn_inbox`'s `Ok` result header in d8
  across the admission calls. When the spawner parked and resumed on another hart, d8 held
  that hart's value, so a successful spawn read as `Err <actor>`. Contexts now save d8..d15
  and QOS A64 apps get native ABI 11 (legacy) / 12 (compact).
- **qos main 03ccd4a** reverts the untested epservice WIP (ba8b176) that aac3edc merged;
  see [2026-11-06-EPSERVICE-REVERT.md](2026-11-06-EPSERVICE-REVERT.md).
- QOS main + e138e65 builds directly. The 5 Nov pairing workaround (trial on 19e15cf) is no
  longer needed.

## Setup

- Worktrees: qos `qos-pte1` (this branch, `fprisc-pin-trial-e138e65`, from main 03ccd4a) and
  fprisc `fprisc-pte1` (e138e65), built with `make fpr`. The main checkouts and
  `sdk-0.4.0-candidate` were not touched.
- Sweep: `FPRISC_ROOT=<fprisc-pte1> sh check-all.sh`, 11:55 to 13:10, exit 1 (the known
  failures).
- Baseline: the 5 Nov baseline sweep (qos 0bf8bee + 1a09f01, 145/9/9), not rerun. It gave the
  same result on 3 Nov and 5 Nov, and neither side of it has changed since.

## Results

Every leg that is not PASS in all three columns. Full table in
`evidence/2026-11-06-fprisc-pin-trial-e138e65/legs-not-green.tsv`.

| Leg | baseline 1a09f01 | 43f02dc (5 Nov) | **e138e65** | Note |
|---|---|---|---|---|
| Storage deadlines, late replies and finite service budgets | PASS | FAIL | **PASS** | qsysfail check 12 fixed |
| qsys failure paths (tests/qsysfail.fpr) | PASS | FAIL | **PASS** | qsysfail check 12 fixed |
| liveboard (std/live end to end) | PASS | FAIL | **PASS** | 5 Nov failure was a load flake |
| Editor and Terminal live preferences | FAIL | PASS | **PASS** | improvement |
| Native instruction ratchet | FAIL | FAIL | FAIL | known. Segment 474 (ceiling 312), runtime call sites 95 (ceiling 67), the same as 43f02dc |
| dedup ratchet | FAIL | FAIL | FAIL | known |
| Graphics.qa | FAIL | FAIL | FAIL | known (timeout) |
| the tree as a toolchain | FAIL | FAIL | FAIL | known |
| Sol NN | FAIL | FAIL | FAIL | known |
| Vec fusion | FAIL | FAIL | FAIL | known |
| Vec fixpoint + write-back fold | FAIL | FAIL | FAIL | known |
| sol Ok/Err tier + txn hygiene | FAIL | FAIL | FAIL | known |
| 9 GL/Xvfb/POS/x28 legs | SKIP | SKIP | SKIP | not runnable on this host |

## Evidence

In `evidence/2026-11-06-fprisc-pin-trial-e138e65/`:

- `legs-e138e65-qos03ccd4a.tsv`: per-leg results. The session's scratch directory, which
  held the raw sweep log, was lost when the session restarted after the sweep. This TSV was
  rebuilt from the baseline rows plus the one leg the sweep's leg-by-leg comparison showed
  as different. The comparison output was captured before the loss and matches the table
  above.
- `legs-not-green.tsv`: three-column comparison with the 5 Nov TSVs.
- `qsysfail-e138e65-4harts.txt` and `qsysfail-e138e65-run1.log`: the 10-run repeat, using the
  5 Nov `qsysfail-runner.sh`.

## Pi 4B deployment

**Status: candidate built and qualified on the Pi; install not yet run.** The installed
session is unchanged (Main PID 17227, `/usr/bin/qosp` b2ae9b56..., the 4 Nov compact-runtime
install). The final install step (`deploy.sh` on the Pi) was held for the user's explicit
approval because it replaces the production install.

The method follows [2026-11-04-PI-COMPACT-RUNTIME-UPGRADE.md](2026-11-04-PI-COMPACT-RUNTIME-UPGRADE.md).
Working files, scripts and logs are in `.qos/validation/pi-e138e65-20261106/` (local, not
committed).

Done so far:

- **Source export.** Clean worktrees at qos 03ccd4a and fprisc e138e65 were exported, using
  the 5 Nov export script. The export's `fprisc.lock.json` names the compiler snapshot
  (`e138e654...+worktree-09e0d165...`). That is an export overlay only; the checkout lock is
  untouched. `qos lock --check` resolved all 311 pins.
- **ARM64 build** in `qos-pi-builder:20261104` (GHC 9.4.7, the GHC 9.8.2 freeze omitted as
  before). It built the compiler, the Main profile with its six apps and seed disk, the
  `qosp-es` host, the runner, the Editor compiler and its SDK, and kms-readback. Portable
  ABI 22, codegen 204, with the same typed-IR options as 4 Nov.
  - The SDK self-test passed: QAR2, publication, invalid source refused.
  - The disk updater tests (20) and the SDK service, publication and signal checks passed.
  - The runtime-qualification builder also needs fprisc `bench/`, which is outside the
    export allowlist. It was added from e138e65 for that build only.
- **Physical runtime qualification** (fprisc `tools/run_pi_runtime_qualification.py`, run
  beside the installed session): **PASS, 2286 cases** in 7 min 45 s, production identity
  unchanged before and after.
- **Staging on the Pi** under `/tmp/qos-pi-e138e65-20261106`: baseline snapshot, then a
  hash-verified transfer (candidate sha256 82ee927d...). The SDK self-test passed on the
  device.
- **Disk preflight** on a copy of the live writable disk preserved all 46 non-onboard records
  and replaced the 7 onboard app/index records (generation 60 to 62), as on 4 Nov.
- **Isolated Main preflight** (`tools/pi4/main-soak.py`, a separate disk, 1024x600, 4 harts,
  120 s): PASS. Seven navigation cycles, RSS 43.6-43.8 MiB, normal quit and SIGTERM clean,
  installed session identical before and after.
- The candidate compiler was stopped and `preflight.ok` written (core manifest
  90136749...). The root filesystem has 62,176 KiB free, about the same as on 4 Nov when the
  install's space check passed.

Still to do once approved: run `deploy.sh` on the Pi. It stops Main and fprd and backs up the
installed files. It writes `/var/lib/qosp/deployment-pi-e138e65-<stamp>/rollback.sh`, then
migrates the writable disk and installs the host, Main, the seed disk and the SDK. It
restarts twice, and the second restart must give a new PID. Last comes a 60 s health check.
Any failure restores the backup automatically. After that come the fresh-SSH verification,
the HDMI readback and a longer health soak.
