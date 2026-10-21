# QOS on the typed-IR compiler

Date: 2026-10-21. Kind: compiler pin and validation record.

`fprisc.lock.json` moves from FP-RISC `4c16996` (codegen revision 55) to
`43ffba2c644d89e2f650ecc3f643d7ba921e4977`. That commit is FP-RISC main
with three branches merged in: M2's direct A64/x86-64 backends with the M1
repairs (codegen revision 67), M3's allocator, and the typed-IR coverage
increments. See FP-RISC `docs/2026-10-21-TYPED-IR-MERGE.md`. The typed-IR
backend stays opt-in (`FPR_TYPED_IR_BACKEND`), so QOS builds still use
the legacy generator. The revision bump changes Base Bool constructors to
load the runtime singletons, and it invalidates every cached unit. The
runtime ABI stays 22. `./qos.py lock --check`: 302 pins, all resolvable,
`fpr.lock` current.

## check-all on this Mac (macOS arm64)

`check-all.sh` on QOS `c44b904` against that compiler ran 162 legs; 5 were
red. Each red leg was rerun on its own with three compilers: the new pin
`43ffba2`, FP-RISC main before the merge `0b6e8df` (codegen revision 55),
and the old pin `4c16996`.

| Leg | Full sweep | Rerun alone: 43ffba2 / 0b6e8df / 4c16996 |
|---|---|---|
| Buildroot service supervision | failed (`no-ready/run/owner` still present) | pass / pass / pass |
| HostedBytecode (sol) | failed | pass / pass / pass |
| qsys: namespace and plugins persist | failed | fail / fail / fail |
| Editor policies | failed | fail / fail / fail |
| Sol NN | failed | fail / fail / fail |

The first two passed when run alone. The machine was heavily loaded
during the sweep (load average about 10 on 10 cores). The other three fail
the same way with all three compilers, so they are not caused by the new
pin or by codegen revision 67:

- qsys: compiling `tests/qsys.fpr` for qa64 exits 1 at the safe/unsafe
  check. The resolved `parse`, `validChars` and `within` are unsafe without
  an `unsafe` signature, and `requestUntil` is marked unsafe but found safe.
- Editor policies: `editorpolicyprocess` with 1 hart ends in
  `qosp: fatal SIGSEGV: addr=0x3` inside the image, after the child's
  32 MiB budget runs out. The pc differs between compilers only by code
  layout.
- Sol NN: FP-RISC's `sol/examples/nn.sol:104` is refused by the
  linearity check (`z1` used twice).

Not run: a Linux host sweep, Pi 4/STAR64 board deployment, and anything
performance-related.
