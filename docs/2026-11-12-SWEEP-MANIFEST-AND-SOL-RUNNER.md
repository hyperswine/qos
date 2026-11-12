# One manifest of legs, and a Sol runner (2026-11-12)

Kind: tooling, tested on the hosted arm64 Mac only. Follows
[PARALLEL-SWEEP](2026-11-12-PARALLEL-SWEEP.md), which this replaces in part:
`tools/sweep.py` is gone and `check-all.sh` no longer holds the legs.

## What there is now

| File | What it is |
|---|---|
| `checks/legs` | every leg: its name, tags, and its bash body. The only list. |
| `checks/sweep.sol` | the runner, in Sol |
| `checks/prelude.sh` | the environment and the three helpers a leg body starts from |
| `checks/selftest.legs` | a manifest with known verdicts, for the runner's own leg |
| `./sweep` | starts the runner with the pinned released Sol |
| `check-all.sh` | eight lines: `./sweep --in-place`, the serial form, for `qos.py` and habit |

    ./sweep --jobs 6 --output build/sweep/<new dir>     # private trees, in parallel
    ./sweep --since origin/main                         # only what a change reaches
    ./sweep --only "Main Profile" --in-place            # one leg, in this tree
    ./sweep --list --changed tests/kbdread.fpr          # what would run, and why

## The manifest

    == name of the leg
    @ serial
    @ with previous
    @ expect fail -- why
    <bash body>

The bodies are the old legs with the `echo "== .. ==" && ( .. ) || leg_failed
"${LINENO:-?}"` wrapper removed; nothing else in them changed. A body runs in
a subshell under `set -uo pipefail` and its exit status is the verdict, as
before. `ran` and `leg_skipped` are as before; `service_leg` reads a service
check's verdict.

**Expected status is in the manifest.** The ten legs that are red on main
carry `@ expect fail -- why`, with what each one actually prints. The summary
separates them from new failures, the exit status is nonzero only for a new
failure, and a red leg that passes is reported as `NOW PASSES` so its line
gets removed. This is what a sweep needed a hand comparison against a dated
note for until now.

    SWEEP: 143 passed, 10 failed, 9 skipped (of 163 legs run; 0 not run), ...
           10 of the failures are expected (`@ expect fail` in checks/legs); 0 are new

## The runner

Sol 0.13.1, the newest released toolchain, pinned in `./sweep`
(`sol +0.13.1`; install with `fprmeta install 0.13.1`). It is never the
compiler under test: `checks/prelude.sh` also removes every `FPR_*` variable
the launcher or the caller's shell set before a leg starts.

It does what `tools/sweep.py` did: private tree per worker, `@ serial` groups
on one lane in file order, `@ with previous` groups in one tree, the service
checks once beside the workers, a new failure run again alone, `--since` /
`--changed` narrowing by the same rule, per-leg seconds in `results.json` and
a `times` file that `--times` reads to start the longest legs first. New:
`--in-place` (no copy, one worker), `--strict` (a skip fails the sweep, the
old `QOS_SWEEP_STRICT=1`), and only *new* failures are re-run alone, so the
ten red legs no longer cost nine minutes of re-running.

Every running leg is a job the script owns (`Proc.start`, a linear value): a
deadline or an interrupt kills the leg's whole process group. Nothing in the
runner is transactional; every read and write is immediate, on purpose.

## Measured

| Run | Wall time | Verdict |
|---|---|---|
| `check-all.sh` serial, this morning | 70 to 75 min | reference |
| `tools/sweep.py --jobs 6` | 27.7 min (9.4 of it re-running red legs) | 144 / 10 / 9 |
| `./sweep --jobs 6` (Sol) | 18.3 min | the same ten red legs, all expected; one new failure, below |

The one new failure in that run was the runner's own self-test leg, on an
assertion that was too tight for a worker's tree (fixed, and the leg passes
when run by itself in a fresh worker; the full sweep was not repeated after
that fix). One leg (Buildroot service) failed beside others and passed alone.

`./sweep --list --changed PATH` answers in about 5 s.

## What the self-test leg checks

`sweep verdicts` runs the runner on `checks/selftest.legs` and requires the
exact counts, the three new failures, the `NOW PASSES` line, the skip note,
the timeout, exit status 1; then a green selection with exit 0; `--strict`;
and six `--changed` cases. `tests/test_legs.py` (was `test_check_all.py`)
still runs real leg bodies from the manifest against stubbed tools.

## Size

Removed: `tools/sweep.py` (415 lines), `tests/test_sweep.py` (83), 326 lines
of `check-all.sh`. Added: `checks/sweep.sol` (484), `checks/prelude.sh` (43),
`checks/selftest.legs` (27), `./sweep` (10). `checks/legs` is 616 lines
against the 334 of the old script, because the multi-line legs and the
comments are now laid out, with one blank line between legs.

## Not done

- **The bodies are still bash.** 33 legs are one script call, 16 are service
  verdicts, about 100 are inline one-liners (build an app, run it, grep).
  A declarative form for those (`app tests/x.fpr`, taking `#: expect` from
  the test) is the next step and would let single-purpose scripts go; none
  were removed here. `tools/` still has its 75 Python and 14 shell files.
- `tools/check-services.py` and its two helpers stay: CI runs them.
- Sol notes from writing this: a recursive function, and everything that
  calls it, needs an `unsafe` signature, so the word scan taints seven
  functions up to the entry point; a clock in seconds only (`timeNow`); every
  immediate effect prints a `[sol] REALTIME` line on stderr.
- In a worker's tree (no `.git`) `--changed` counts generated files as
  leaves. That only over-reaches.
- Not run on Linux; there is no released Linux toolchain to pin there.
