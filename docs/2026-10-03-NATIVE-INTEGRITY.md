# Native ABI and image integrity follow-up

Date: 2026-10-03. Kind: implementation record. FP-RISC pin:
`da365684309cebb36c8236c7ddb3855c95339f1f` (codegen revision 34,
native ABI 2). Follows the native image, failure-honesty and vector audits.

## Runtime migration

The vector header grew when product recipe metadata was appended. Existing
field offsets stay unchanged, but its size is part of the native runtime ABI.
FP-RISC now stamps native ABI 2. QOS refuses ABI-1 process images and requires
rebuilding the kernel, runtime and process images together. Portable application
ABI 18 is unchanged.

Integration exposed a signed recursive mailbox typing regression in the vector
layout changes. FP-RISC now records clause body types for layout evidence without
connecting the separate declared recursion placeholder. Signed generic vector
construction and unsafe heterogeneous mailbox recursion have regression fixtures.

## Integrity before placement

The launcher supplies IMAGE, RELOC and optional IMPORT extents plus the LOAD
hash claims to `Sys.checkImage`. This preflight runs before reserving a process
pid or recording endpoint grants. `Sys.placeImageAt` repeats the same gate before
requesting the buddy block, copying instructions, relocating or publishing them.
The gate checks the native ABI, archive spans, LOAD consistency and both hashes.
Missing hashes are refusals, rather than an unchecked compatibility mode.

IMAGE is hashed directly from its archive span. RELOC and IMPORT are hashed as
the concatenation of their spans using a streaming SHA-256 implementation; no
concatenated buffer or image backing allocation is required. That implementation
also supplies Portable's existing single-span SHA function.

Native process imports remain unsupported. A nonempty IMPORT section first has
its digest checked and is then explicitly refused, including when its hash is
valid. Native builders currently produce self-contained images.

Endpoint grant errors also stop launch instead of logging and continuing.
A later placement failure, such as exhaustion after grants were recorded, still
needs grant rollback. Grant removal on process exit is separate remaining work.

These checks establish integrity against supplied LOAD claims. They are not
signatures or producer certificates: a producer can recompute claims. The C
primitive trusts the launcher's supplied metadata, and native process execution
remains trusted code rather than isolation.

## Executable evidence

`tools/native-integrity-check.py`, now a `check-all.sh` leg, compares single-span
and split-span SHA against Python's independent implementation at padding and
block boundaries. A real RV64 process exercises generic vectors, nested float
message copying and a captured fold. QEMU runs both virtio modes on one and two
harts. Mutated IMAGE, RELOC and IMPORT bytes, missing IMAGE/RELOC digests, ABI 1,
and a correctly hashed unsupported IMPORT are all refused by preflight and
placement with zero image allocation attempts. The valid process requests one
image block and returns it after exit. A production object check confirms the
allocation counter exists only in test builds.

The complete FP-RISC Base suite and vector-limit suite passed. QOS's existing
native memory admission tests passed on one and two harts. The lock check found
all twelve module pins resolvable with no module lock change.

The SDK pin was written from verified HEAD after committing tracked compiler
changes. The usual pin helper requires a wholly clean checkout, including
unrelated untracked files; those files were preserved rather than included in
the SDK commit. The pin identifies native ABI 2 at SDK revision `da36568`.

Additional integration checks passed: QOS smoke 16/16 (including LiveView local
networking), two-boot qsys persistence, concurrent image lifetime/reclamation,
native storage refusal and fail-stop injections, Main Profile real GL with two
boots, and both real graphics games with focused input and close/restart. The
FP-RISC standard-library and case/signature/measure suites also passed. This
slice ran these focused legs rather than claiming a complete check-all sweep.

Graphics captures and logs are retained under `/tmp/qos-abi2-shell` and
`/tmp/qos-abi2-gfx`; native corruption logs are under
`/tmp/qos-native-integrity-overflow`. The graphical test processes were closed.

The native launcher endpoint test passed: granted display and clock access,
named refusal of an ungranted pin, and process-scoped storage round-trip.
Type-changing typed-vector checks passed on Portable and RV64 Native.
