# The three red check-all legs, fixed

Date: 2026-10-22. Kind: fix record and compiler pin.

The [typed-IR compiler pin](2026-10-21-TYPED-IR-COMPILER-PIN.md) left three
check-all legs red that also failed on the previous pin. Each has a fix
here or in FP-RISC, and `fprisc.lock.json` moves from `43ffba2` to
`0c9c8b73eceece62e17992da006a5995abebfd6c`, which carries the FP-RISC
side (FP-RISC `docs/2026-10-22-MERGE-REGRESSIONS.md`).

## qsys: the safe/unsafe line

`tests/qsys.fpr` was refused at the safe/unsafe check. Two causes, both in
modules from 2026-10-20:

- The live policy and preference parsers (`apppolicy`, `fileaccesspolicy`,
  `editorpreferences`, `terminalpreferences`, `runpolicy`, `editorstate`,
  `preferencestore`) call `policytext`'s unsafe parsers without an
  `unsafe` signature. They now have one, as `filepolicy` got in `6fb3dde`.
- `std/storageclient`'s `requestUntil` was marked unsafe, though the
  analysis finds it safe, which made its caller `within` unsafe. The
  marker is dropped.

`fileaccesspolicy`'s `validChars` was recursive without a measure; it now
counts down with `measure n`, so `canonical` and its callers stay safe
rather than spreading `unsafe` up the chain.

## Editor policies: a fault at address 0x3

`editorpolicyprocess` faulted after a confined child exhausted its budget.
The FP-RISC module registry grew its slot arrays from the calling actor's
heap, which was reclaimed while the registry still used it; FP-RISC now
allocates them from memory owned by no process. QOS also freed a launched
plugin's image without removing its module table from the registry;
`plug_image_quiet` now calls `fpr_mod_detach` first
(`qos/appside/entry.c`). With only the allocation reverted, the fault
returns at `addr=0x3`.

## Sol NN

FP-RISC's `sol/examples/nn.sol` used the matrix `z1` twice; it now reads
its rows before the relu map consumes it.

## Validation (macOS arm64)

| Check | Result |
|---|---|
| `./qos.py lock --check` | OK, 302 pins resolvable, `fpr.lock` current |
| `check-all.sh` against FP-RISC `0c9c8b7` | 162 legs, all green |
| FP-RISC `tests/check_base.py` at `0c9c8b7` | 105 jobs, exit 0 |
| FP-RISC CI, [run 39620437639](https://github.com/hyperswine/fprisc/actions/runs/39620437639) | success; the typed-IR x86-64 backend executed on Linux, 47/47 strict native |

The two legs that were flaky under load in the previous sweep passed too;
this sweep ran at a load average near 2.5 on 10 cores.

Not run: a Linux host sweep of QOS, Pi 4/STAR64 deployment.
