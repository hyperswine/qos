# The sweep, several legs at a time (2026-11-12)

Kind: tooling, measured on the hosted arm64 Mac (10 cores). Nothing here was
run on Linux or x86-64.

`check-all.sh` runs its 163 legs one after another in one tree and takes
70 to 75 minutes here. This adds `tools/sweep.py`, which runs the same legs
several at a time, and an object cache that shortens every app build.
`check-all.sh` is unchanged as the serial reference and stays the only list
of legs.

## Measured

| Run | Wall time | Verdict |
|---|---|---|
| `check-all.sh`, serial (this morning, pin trial) | 70 to 75 min | reference |
| `sweep.py --jobs 6`, first run | 27.6 min | 4 legs failed only because of missing grouping (below) |
| `sweep.py --jobs 6`, final | 27.7 min, of which 9.4 min re-running the red legs alone | 144 passed, 10 failed, 9 skipped |

The final run's ten failures are exactly the ten that are red on main
serially (the nine standing ones and the native instruction ratchet). On a
green tree there is nothing to re-run, so the same sweep is about 18 minutes.

One warm app build (`make qos-app PROG=tests/filessvc.fpr`), same image bytes:

| | Seconds |
|---|---|
| before | 23 to 24 |
| with the object cache | 9 to 10.5 |

## What a warm app build was spending

Timed step by step, with every compiled unit already cached:

- 9 s in `fpr` itself. Cached units save code generation only; parsing,
  checking and placement of the whole program still run. **This is now the
  largest cost and is not addressed here**; it needs a compiler change (a
  whole-compile result keyed by the inputs read).
- 3 x 4.8 s in the three links (export pass, image, moved image). Each one
  recompiled the same 13 runtime C files and re-assembled the same units.

So sharing the compiler's unit cache between build directories, which was the
plan, would have saved almost nothing: a build in a fresh directory with the
units shared measured 24.7 s against 23.0 s warm in place.

## The object cache (`tools/ccobj.py`, `QOS_OBJ_CACHE`)

The x86-64 and AArch64 app rules in `qos-app.mk` now compile the program,
its units and the runtime sources to objects once and link the objects three
times. An object's name is the SHA-256 of the compiler's version, the flags
and the source as the preprocessor sees it under those flags (plain `.s`:
its bytes), so a changed header, macro or path is a different object. Objects
are written whole by rename, so builds running together are safe.

`QOS_OBJ_CACHE` defaults to `$(BUILD)/rtobj`. The sweep points every tree at
one cache. The `.qa` and the ELF are byte-identical to the old rule's
(compared for `tests/filessvc.fpr` on AArch64). The RISC-V app rule, plugin
rules, `build-process-app.sh` and the native kernel build are not converted.
The x86-64 rule is converted but was not run here.

Compiler warnings for the runtime print only when an object is first built.

## The runner (`tools/sweep.py`)

    python3 tools/sweep.py --output build/sweep/<new dir> [--jobs N]
        [--since REF] [--only TEXT] [--times results.json] [--list]

- **Private trees.** Each worker has its own copy of the tree (the same
  snapshot the service checks use), its own `TMPDIR`, `CK_TMP`, disk and
  cache directory. Legs run exactly as written in `check-all.sh`.
- **Serial lane.** A leg that names a fixed `/tmp` file, or is marked
  `# sweep: serial`, runs on one lane in file order. Marked: the Main
  Profile and Graphics.qa legs (two real windows at once fight over focus)
  and the Buildroot service leg (timing assertions).
- **Groups.** A leg marked `# sweep: with previous` uses what the leg above
  it built and runs right after it in the same tree. Five legs needed this:
  QOSPortable host+run and QAR2 integrity (`app.qa`), QAR2 process load and
  Transparent ACBs (the native kernel), liveboard LiveReload. The serial
  sweep hid these dependencies.
- **Service checks** run once beside the workers and their legs read the
  verdicts, as in `check-all.sh`.
- **Failed legs run again alone.** A leg with a deadline can miss it only
  because other legs took the cores: three did in the final run (Buildroot
  service, failure injections, native image integrity) and passed alone.
  They are counted as passed and listed under a NOTE; `results.json` keeps
  both verdicts (`first`). `--no-retry` turns this off.
- **Times.** `results.json` has each leg's seconds; the summary prints the
  ten slowest. `--times` starts the longest legs first.

Slowest legs alone or lightly loaded: Main Profile about 10 min, Graphics.qa
4 min (it fails at its deadline), failure injections 3 to 4.5 min, MVU reload
2 to 4 min, development publication 1.5 to 2.5 min. The service checks are
the floor for the whole sweep: about 16 to 18 minutes at their two workers.

## Only the legs a change can reach (`--since REF`)

The rule is deliberately narrow, and a leg that is not run is reported as
not run, never as passed:

- `docs/` and `*.md` reach nothing.
- Anything outside `tests/`, `tools/` and `docs/` (a program, the runtime, a
  makefile, a lock file, `check-all.sh`) reaches every leg. So does a tool a
  makefile names.
- A test or tool reaches the legs that name it, directly or through a script,
  an import, a table of check names or a `use`. One that no leg names
  reaches every leg.

Examples on this tree: `tools/guishell-check.py` and `tests/gfxshare.fpr`
1 leg each, `tests/filessvc.fpr` 2, `tests/kbdread.fpr` 2 (its own leg and
the sweep's self-test, which names it), `tests/appsession.fpr` 45 (every
service leg reaches it through the shared check table),
`programs/mods/editapp.fpr` 163.
Names are matched as words, which over-reaches and never under-reaches for
files directly in `tests/` or `tools/`; a nested file is matched by its last
two path components.

`tests/test_sweep.py` checks the leg parsing, the tags and these rules, and
runs in the sweep's own first leg.

## Not done

- The compiler's 9 s per warm build.
- The other build rules listed above.
- FP-RISC's own suite (173 checks) is untouched.
- The service checks still copy a tree per check and stay at two workers.
- No run on Linux, in CI, or with a different `--jobs`; six workers plus two
  service workers already made three deadline legs miss on ten cores.
