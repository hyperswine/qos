# MVU live reload integration

Date: 2026-10-04. Shared design and implementation status live in FP-RISC:
[the runner slice](../../fprisc/docs/2026-10-04-LIVERELOAD-RUNNER.md).

`std/mvureload` reads a named app archive through the Files service, then supplies
`Plug.attach` to FP-RISC's `std/reload.attachAt`. QOS retains archive retrieval
and executable image placement; the shared library owns baseline-scoped
compatibility and lookup. This adapter does not persist `sys/live`.

`tests/livereload.fpr` now runs a single MVU model actor. Its env holds an
explicit record of module functions and their adopted table. The runner handles
`EReload`, calls the adapter between turns, adopts the complete env on success,
and supplies it to update and the persistent render worker. The app's update
ignores successful reloads; its accumulator still reaches 108. A failed
replacement produces `EReloadRefused` while keeping v2 usable.

The test attaches an unrelated module before swapping math, catches a missing
archive and an invalid baseline before placement, refuses arity drift, checks
renderer results across frames, and calls an old saved v1 function after v2
is active. `tools/mvu-reload-check.py` runs it on one/four harts and checks state,
registry count, old closure and refusals. `check-all.sh` invokes that tool.

Compatibility remains arity/export-only. Metadata uses archive IDs as test
version labels; certified interfaces and content-hash identity are still needed
before automatic watcher-driven patch adoption. There is no new replay path,
POSIX attachment implementation, image reclamation, native RV64 reload test or
browser/GL reload integration. The old loader/livereload modules remain for
existing consumers and replay. The compiler pin identifies FP-RISC revision `03f4a38`, which contains the
shared runner and attachment gate.
