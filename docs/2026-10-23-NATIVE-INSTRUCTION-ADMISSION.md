# Native instruction regression admission

Kind: living compiler-consumer contract, version `native-insns-v1-ratchet-1`.
This supersedes the shared-RISC instruction discussion in the historical
embedded help corpus. It does not change the native runtime ABI or claim
hard real-time admission.

`check-all.sh` now invokes FP-RISC's `tools/native-insns-ratchet.py` on
`programs/system.fpr`, with independent RV64 ceilings:

| Quantity | Ceiling |
|---|---:|
| Maximum native target instructions per function segment | 312 |
| Maximum static runtime call sites in one function | 67 |

The fresh typed baseline contains 1,669 functions across 27 assembly files,
including the root and all linked units. Its maximum exit tail is 256
instructions; its total static runtime call-site count is 7,763. The previous
200-shared-RISC-instruction ceiling is retired rather than converted by an
assumed architecture multiplier.

## Required evidence

The compiler must emit strict typed code for the complete linked closure.
Each generated function needs one matching finite `native-insns-v1` row.
The gate rejects missing units, reports or headers, unknown metric versions,
duplicate rows/symbols, unbounded paths, target mismatches and legacy input.
Data-only units need no function row. A missing tool or failed command fails
the sweep; its stdout is not the verdict.

Ceilings are regression controls with explicit units. Raising either requires
fresh evidence and review of the changed functions. The gate prints runtime
call-site counts separately; a larger runtime-call surface cannot hide behind
an unchanged instruction count. Compiler revision, native selection policy
and target must accompany the evidence. The compiler release pin identifies
the toolchain that supplies this gate: FP-RISC `afebff101790`, codegen 76,
RV selection 16. That compiler also includes the validated builtin manual/GC
and ARC/raw migrations; its runtime contracts remain profile-specific.

## Timing and call/return limits

The instruction metric applies to each selected function's CFG after
allocation/frame expansion, with conservative unrelaxed RISC-V pseudo costs.
It counts neither C/HAL internals nor target cycles. Static `ccalls` includes
slow-path call sites and is not a dynamic execution count or a time bound.

Individual function rows also do not compose return chains. A callee's
exit tail can join a caller continuation without another entry tick;
multiple returns can accumulate work. Thus the maximum individual segment
is not itself a global between-safepoints or scheduler-latency certificate.
The JSON result explicitly records runtime time bounds and call/return
composition as `unprovided`, and an elapsed-time certificate as false.

The scheduler continues to count fuel events and actor admissions using its
existing runtime contract. A formula such as fuel quantum times this maximum
alone does not prove a wall-time deadline. Hardware instruction timing, bounded
runtime calls, return-chain composition, allocator/ARC work and scheduler
overhead must be supplied before hard latency admission can be claimed.
No new runtime deadline guarantee is introduced by this regression gate.

The old generated `programs/mods/docsdata.fpr` is an archived help corpus;
its literal contents and module identity remain historical. This living
reference states the current executable gate and takes precedence over
that old `# wcet:` model.

## Reproduce

Select the matching FP-RISC checkout with `FPRISC_ROOT`, then use the same
home, path and foreign declarations as check-all:

```sh
export FPR_HOME="$PWD"
export FPR_PATH="$FPRISC_ROOT"
export FPR_FOREIGN="$PWD/core/foreign.fpr"
python3 "$FPRISC_ROOT/tools/native-insns-ratchet.py" programs/system.fpr \
  312 rv64 --runtime-call-sites-ceiling 67 --json-output /tmp/qos-native.json
python3 -m unittest discover -s tests -p test_check_all.py -v
```

Focused validation passes the actual gate, both real ceiling regression
controls, 13 unit tests, all 302 module pins and the graphics-independent
compile suite. [Evidence](evidence/2026-10-23-native-metric/metadata.json)
records their scope. FP-RISC passes its 116-job Base sweep at this pin.
The workflow now requires the native gate, but hosted CI has not run here.
This is not a full QOS check-all or physical board run. Final legacy codegen retirement still
requires the wider platform acceptance gates.
