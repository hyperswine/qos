# Typed vectors in QOS

Date: 2026-10-01. Integration record for FP-RISC's `Vector a` migration.

QOS now declares its TUI, launcher and voxel buffers as `Vector Int`.
Their reads and writes share that element type; an incompatible element
is refused at compilation. The TUI row-list signatures also now declare
their actual Int elements. Linear buffer consumption remains enforced.

The updated TUI is published as `tui.v2.0#51748af84a3e003b`; the launcher,
frame test and dependency lock use that exact module. The compiler release
pin records the accompanying FP-RISC implementation commit.

`tools/typedvector-check.sh` executes the shared FP-RISC fixture through
Portable A64 and Native RV64 with two QEMU harts. It checks generic functions
on existing Int and F64 vectors, representation-preserving generic maps,
type-changing maps and float constructors. This gate is part of
`check-all.sh`, alongside the existing vector, float, TUI and actor gates.
FP-RISC's Base suite supplies the negative element/layout/linearity checks.

Native construction and type-changing mapping require a concrete output
element layout. Generic operations on an existing vector preserve its
layout; generic allocation still needs future layout evidence. See
FP-RISC's `docs/2026-10-01-TYPED-VECTORS.md` for the contract and migration
limits. `Vector _` is an inference hole, not an untyped storage escape.

The diagnostic-anchor gate now uses isolated temporary fixtures and captures
the compiler's exit status and output directly, making failures inspectable.
The old pipeline gate failed during a broad run but passed in isolation;
the cause of that intermittent failure was not established.

The voxel source signatures are migrated, but this does not certify that
standalone demo's unrelated inputPoll and incomplete-pattern issues.

Validation: typed-vector execution passed on Portable A64 and Native RV64
QEMU; smoke passed 12/12. The full sweep passed its runnable functional
gates. Its frontend size guard failed at the old 125-line ceiling, then
passed separately with the explained 126-line ceiling for the new profile
flag. Graphics/window legs, websocket prerequisites and alternate A64
cross-tools were skipped; GPU-requested comparisons used the fallback.
