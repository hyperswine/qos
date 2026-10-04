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

The runtime now compares checked inferred types, full written contracts and
compiler/runtime ABI context for trusted compiled images. Same-arity type,
precondition and work-bound changes refuse, as do unsafe/uncertified exports.
Unchanged checked contracts and private specialization changes can reload.
Scoped binding resolves root exports, so dependency names cannot impersonate
them. See [runtime interfaces](../../fprisc/docs/2026-10-04-RUNTIME-INTERFACES.md)
for the schema, trust boundary and regression coverage.

The image schema requires rebuilding plugins and hosts together: FP-RISC
codegen revision 36 and native process ABI 3. Notes now declares its intended
string-only edit interface in both versions. The native integrity test rejects
the previous ABI 2 before allocation and still runs valid vector processes.

The version-aware adapter now checks event `from`/`to` against compiled root
source identities, keeping archive addressing separate. See
[reload identity](../../fprisc/docs/2026-10-04-RELOAD-IDENTITY.md). The real MVU
fixture uses these source hashes and covers stale-event refusal before retrieval
and wrong-image rollback. Production watching/publication is still open. There is no
new replay path, POSIX attachment implementation, image reclamation, native
RV64 reload test or browser/GL reload integration. The old loader/livereload
modules remain for existing consumers and replay, including their global-newest
baseline limitation. The new adapter uses an explicit per-module baseline.

The compiler pin is `dedafa544db26a8c71bd4a26ea69919501a826a7`, containing the shared runner, checked commit
interfaces, checked runtime module interfaces and version-aware source identity
matching. Unrelated untracked files in
the compiler checkout are excluded from this milestone.

Executed verification for this milestone: real plugin reload and checked
contract/specialization patches passed on one/four harts; Notes passed; native
integrity/vector process checks passed on one/two harts with both virtio
variants; focused MVU and multi-client LiveView smoke passed. FP-RISC's complete
Base suite passed. The full QOS check-all sweep was not run.

The identity-aware increment passed the complete FP-RISC Base suite and shared
MVU runner variants, plus real QOS reload/refusal tests on one/four harts.

POSIX attachment and the production shared MVU clock are now implemented in
[POSIX-RELOAD](../../fprisc/docs/2026-10-04-POSIX-RELOAD.md). QOS's MVU driver
uses its timer HAL through `Sys.mtime` rather than reading cfg.mt directly;
units and pacing remain unchanged. Current sibling-compiler tests pass real
QOS reloads on one/four harts and focused MVU/LiveView smoke (2/2). This new
compiler milestone is committed and pinned, including native module attachment
and the production clock.

## Host publication and watching

The compiler pin also includes `fpr publish`, `fpr watch`, and `std/watch` for
immutable POSIX image publication and typed MVU notifications. Its targeted
publication suite passed on one/four harts, including real runner adoption and
failure recovery. See [publication contracts](../../fprisc/docs/2026-10-04-PUBLICATION-WATCH.md).

QOS app-store/qlog publication and watcher delivery now use a separate platform
adapter. The host journal is not a `.qa` distribution format.

QOS publication and runner-owned watcher delivery now have an implementation and
an executable two-boot fixture. See [QOS publication](2026-10-04-QOS-PUBLICATION.md)
for storage ordering, ownership, failure coverage and remaining boundaries.
