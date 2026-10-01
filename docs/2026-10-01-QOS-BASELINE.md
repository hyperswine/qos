# QOS baseline: fixed actor runtime, explicit LiveView safety, dynamic-slot checks

QOS pins FP-RISC `d3d5230bf1999f9b542031ca09aad55700cd897c`
(the complete revision is authoritative in `fprisc.lock.json`). This includes
the concurrent channel-claim Result-loss repair, scalar F64 fast paths,
preserved-register locals and external-request lifecycle fixes. The lock was
first advanced to the actor repair and then updated with `./qos.py fprisc --pin`
after committing the complete compiler/runtime batch.

## LiveView safety

The unmarked wrappers around LiveView's recursive parsing and service helpers
were rejected by the compiler after the import-trust repair. The driver now
carries explicit `unsafe` signatures through those call chains, including
`server` and `serve`. The `tests/mvuweb.fpr` entry declares `main : unsafe String`.
Here `unsafe` means the compiler cannot establish the recursion/WCET bound.

The trust manifest is unchanged. Removing the test caller's `main` declaration
still produces `main is unsafe`; compiling the driver no longer requires a new
allow-list exception. The two-client HTTP/session/reshape/shutdown test passes.

## Dynamic slots

`scene2d` stores entities and slots in the same `Gfx` sum type. `dynGo` and
`diGo` only matched `Sl`, so the graphics fixture was rejected for missing
constructor alternatives. Both loops now explicitly reject a non-slot entry
with a named error. Valid slot behavior and the packed vector's linear ownership
are retained.

`tools/baseline-compile-check.py` checks `gl2d` and `mvuweb` without any graphics
library, window, GPU or X server. It also checks refusal of an unmarked LiveView
caller and runs malformed dynamic lists through both rendering paths, expecting
the named panic. Runtime probes use a temporary working directory and build a
matching Portable host first: otherwise a compiler-revision bump can make an
old shell refuse the app before the intended failure path is reached.

The new gate is an unconditional `check-all.sh` leg, ahead of graphics execution
legs. F64 differential/native/backend checks are also active in the sweep.

## Baseline honesty

The dedup leg used `ratchet | tail -1`, losing the ratchet's nonzero status.
The sweep now executes the ratchet directly. Its reviewed ceilings are 125 lines
for Sol's inference shim (profile primitive declarations) and 244 for the
language shim (qualified module-splicing repairs). Both remain enforced;
parser, inference, desugaring and lifting are shared rather than restored forks.
The reasons for recalibration are recorded in FP-RISC's ratchet script.

## Verification

Before the F64 compiler changes, `./qos.py test` passed 11/11 checks, including
LiveView. The graphics-independent gate passed with the final compiler too:
both fixtures compile, the unmarked caller is refused, and malformed dynamic
entries panic by name in both paths. The final `./check-all.sh` sweep exited 0
with `ALL LEGS GREEN`, including the F64 C-reference probe on RV64/QEMU. FP-RISC's
complete base and standard suites also passed. Verification used the compiler/runtime subsequently committed as the revision
in `fprisc.lock.json`; the final pin includes the complete tested batch.

Unavailable legs remain explicit: Python websocket checks, alternate AArch64
cross-execution, and windowed graphics checks lacked their prerequisites. GPU
capture checks compared the fallback because GPU dispatch was unavailable.
The legacy Sol example tally remains 38/47 and is informational, rather than
a claim that all 47 pass. These compile checks do not establish graphics
rendering on hardware.
