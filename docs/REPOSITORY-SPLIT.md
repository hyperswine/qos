# QOS / FP-RISC repository split

This is a structural separation from monorepo commit
`8936d1967e654304ff12755219e7e380583763f1`. The original `qos-fpr` checkout remains
untouched. The obsolete, separately backed-up `FP-RISC` checkout was removed at the
owner's request. New local repositories are `fprisc` and `qos`, both on `main`,
with the original history and tags retained and no push remotes configured.

## Ownership

| Area | Owner |
| --- | --- |
| Haskell compiler, native backends, Sol VM/JIT and C compiler shims | fprisc |
| Prelude, actor/lens/MVU/general library, Sol library | fprisc |
| Allocation, values, application, actors, vectors, context switching | fprisc |
| Standalone RISC-V machine HAL | fprisc (also consumed by QOS Native) |
| Portable host, native process entry, application HAL/ABI | qos |
| App/process/ELF/QAR loaders | qos |
| Unix graphics, sound, input, networking and block devices | qos |
| Kernel, service programs, applications, manifests, assets | qos |
| fs/timer/uart/compile/loader/livereload service-client libraries | qos |
| Language/runtime tests and tools | fprisc |
| OS/service/device tests, app/disk packaging tools, combined test sweep | qos |
| qos.py, installation, bundling and release configuration | qos |

`SPLIT-MANIFEST.json` records every original tracked file's destination except the
root ignore file (replaced by repository-specific rules). Makefile recipes were
additionally extracted into `qos-app.mk`. Language documentation is in
`fprisc/docs`; QOS documentation stays here. Legacy prose may still use monorepo
paths or the combined product name; the new READMEs and this guide define current
checkout layout. Historical release names and installed `libexec/qos-fpr` paths
are retained for compatibility.

## Explicit dependency

One path names the separate compiler checkout, found in this order: `--fprisc DIR`
on a `qos.py` invocation, `$FPRISC_ROOT`, `fprisc.path` in the QOS tree (written
by `./qos.py fprisc DIR`, ignored by git), then a sibling `../fprisc`. `qos.py`,
the QOS Makefiles (`dependency.mk`) and the host checks use that path directly;
no source symlinks, copies or compiler wrappers are generated, and `./qos.py
fprisc` reports what was found and how.

The repository root now holds the QOS-owned programs, service clients, tests, resources
and application build rules. Language tests and tools are accessed at their actual
paths under `FPRISC_ROOT`. The runtime and machine HAL are compiled there too.
QOS no longer includes the language Makefile as if its files were locally present.

Cross-repository library imports use names such as `std/mvu` and `std/actor`.
The compiler checks importer-relative paths first, then `FPR_HOME`, then the
platform-separated `FPR_PATH` roots. Both the native compiler and Sol use this
lookup. QOS sets its own module home and adds the language checkout as a search
root; pinned service blobs remain in QOS's `.fpr` store.

An installed distribution bundles FP-RISC in a separate `toolchain/` directory
and selects it automatically. Its sources are ordinary copied distribution files,
not development symlinks; the installed toolchain does not depend on either checkout.

This does not remove QOS target support from the compiler, redesign the existing
runtime profiles, settle Actor/Vector language membership, or create a POSIX
backend. Those can now be developed against an explicit ownership boundary.

## Git and releases

Commit the fprisc side first, run `./qos.py fprisc --pin` in QOS, then commit QOS
including `fprisc.lock.json`. Development accepts a dirty or newer compiler
checkout. Releasing requires a clean compiler at that exact pin (`./qos.py
release` checks). Release manifests include the compiler revision as well as the
QOS revision.

The monorepo GitHub tag workflow is archived in `docs/history/monorepo-release.yml`:
it cannot truthfully build two repos from one checkout. Before enabling publication,
create/configure the new remotes and update CI to check out QOS and the exact pinned
fprisc revision, set `FPRISC_ROOT`, test, then package. Existing tags are historical
monorepo tags, not new split releases. No remote repositories or releases were made.

## Validation

The original split passed compiler, Sol scripting, RISC-V/QEMU, native kernel,
portable host, application build and installation checks. The environment-based
revision additionally checks:

- Explicit dependency configuration, missing/invalid environment handling, bundled
  installation selection, and clean/pinned release checks.
- Development watching follows external modules; in-checkout templates use library search names.
- Module home precedence, additional root ordering and missing-module handling.
- Portable host, native kernel, and application bundle builds without source links.
- QOS MVU libraries compiled natively and interpreted through the separate language tree.
- Module lock verification and the host buddy allocator checks.
- Installation into a temporary prefix, followed by creating, bundling and interpreting
  an app from another directory with development environment variables unset.

Actual QOS Portable execution on this Mac previously failed to map its arena at
`0x400000000`; the original unchanged monorepo host reproduced it. This change does
not claim to resolve that runtime issue. The full Linux-oriented integration sweep
and Raspberry Pi hardware checks have not been run.
