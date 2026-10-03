# Memory admission on the shared QOS runtime

Date: 2026-10-03. Kind: implementation and verification record.
The compiler/runtime revision is `f1ea8b7`, recorded in
`fprisc.lock.json` accompanying this change. It includes the recent vector descriptors/kernels and the initial
admission implementation described in sibling FP-RISC's
[MEMORY-ADMISSION](../../fprisc/docs/2026-10-03-MEMORY-ADMISSION.md).

## Initial admission

A loaded native process can now use `AC.spawnWithHeap bytes entry`. The plane
reserves the heap, initial stack, allocator metadata, static channel block,
entry copy and ACB before publishing the actor. Failed reservations roll back
and return `Err`. Cancellation of a parked spawner releases reservations;
a memory grant arriving after cancellation is returned safely.

The declared bytes still cap only the actor-local pool. Initial infrastructure
is admitted from separate control resources. This is a useful foundation for
whole-actor admission, not a completed total-memory policy or a replacement
FP-RISC `Memory.qa` service. Ordinary local allocation and reset retain the heap
grant; exhaustion ends only that actor. Message and stack-growth allocation,
scratch arenas and bounded growable policies remain follow-up work.

## Runtime compatibility and baseline repair

Native process archives now carry `nativeabi <version>` in LOAD. Packaging
reads `FPR_NATIVE_ABI` from the runtime header. The native placement call includes
that declaration; the loader refuses missing/mismatched versions before image
allocation or execution. Version 1 covers the current shared actor/pool/vector
structures and scheduler table. Portable images keep their existing LOAD/nums
contract; their host and application runtime were rebuilt together.

ABI declarations are compatibility metadata for cooperative code, not security
certificates. Existing native process archives must be rebuilt. Bump the version
when shared runtime structures change incompatibly.

The source allow-list was missing the newer endpoint/service modules and the
exact committed actor library they use. They are now explicitly listed in
`core/trusted-modules.txt`; unrelated imports and arbitrary store blobs receive
no blanket trust. This repairs the `qdisk2` compilation failure with the updated
compiler. Redundant unsafe markers on the native kernel's acyclic wrappers
were aligned with that explicit library policy; recursive functions retain
their required markers. `./qos.py lock --check` still checks source module pins separately from
the compiler revision.

## Verification

Fresh on macOS Apple M4:

| Check | Outcome |
| --- | --- |
| `tools/admission-check.sh` | RV64 QEMU, one/two harts: missing/mismatched ABI refused with no image; real process admission, invalid/oversized refusal, local vector/reset work, inherited pid, child-only exhaustion, later child, escaped capture = 42; images return to zero and memory returns within 512 KiB |
| `qos.py run tests/nativeabi.fpr` | Valid declaration accepted; absent, duplicate, negative, oversized, missing-value and trailing-junk declarations refused by parser |
| `qos.py native --smoke` | Normal native kernel builds with the strict checker; launcher up in QEMU |
| `qos.py test` | 15/15, including LiveView with localhost networking enabled |
| `tools/qsys-check.sh` | Two boots HOLDS; notes persist and double from 3 to 6 bytes |
| `tools/nativeimage-check.sh` | Concurrent processes intact; lingering child holds its image until quiescence; reclamation HOLDS |
| `tools/failure-injections-check.py` | Console probe and twelve native boots passed: network stalls/orphans and native storage refusal/death, virtio v1/v2, one/two harts |
| `tools/gfxapps-check.py` | Real GL, two real games, focused input, close/restart and automated checks of five pixel captures HOLDS against the new vector runtime |
| FP-RISC Base and admission runners | Full Base passed; six refusal prefixes and both late-reply cancellation boundaries verified on one/four harts |

The admission and ABI parser legs are in `check-all.sh`. The full repository
sweep, Pi hardware, native graphics and worst-case target latency were not run.
Local socket tests initially failed under the sandbox's networking restriction;
they passed with localhost access enabled.

## Where to go next

The next policy should declare heap, stack and communication reserves separately,
then admit them as one transaction and carve locally. Account for stack growth,
mailbox/message payloads, borrowed or escaped subregions, and scratch arenas.
Keep shared runtime-control reserves explicit. Bound exceptional growth with an
initial and maximum grant, and expose counters distinguishing admission traffic
from ordinary local allocation. A fixed total budget is credible only when none
of those hidden paths can obtain uncharged backing memory.
