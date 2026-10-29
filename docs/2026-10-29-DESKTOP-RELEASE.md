# Matched desktop binary releases

The first package targets macOS ARM64 and macOS 27 or newer, matching the
actual Mach-O deployment targets of the tested compiler and hosts. It ships
one matched compiler/SDK/runtime/Main snapshot. FP-RISC still owns its compiler
and standard library; QOS records the pinned compiler revision and hash.
Other platforms and older macOS versions need their own builds and acceptance.

The `qos-portable` Homebrew formula uses a release tarball, not a source build.
It declares Python 3.14, LLVM, lld, libgit2, libarchive and GLFW; wrappers put
the required tools on PATH. It needs neither GHC/Cabal nor QOS/FP-RISC source
checkouts. Apple's system frameworks remain platform dependencies. The
separate source contributor toolchain and its `qos-fpr` formula are retained;
the command names conflict, so the formula refuses co-installation.

## Building a release

Build the pinned FP-RISC binary, both hosts, Main profile and acceptance driver
using the existing contributor commands in the [SDK guide](2026-10-29-INSTALLED-DESKTOP-SDK.md).
Commit and sync both repositories before staging. The prebuilt profile and
driver must use the same native ABI and API/session as the selected compiler
and SDK. Then:

```sh
python3 tools/stage-portable-sdk.py --fprisc ../fprisc \
  --profile .qos/sdk-profile --output /tmp/qos-release-sdk
python3 tools/compiler-licenses.py --plan ../fprisc/dist-newstyle/cache/plan.json \
  --output /tmp/qos-release-notices
python3 tools/package-portable-sdk.py --sdk /tmp/qos-release-sdk \
  --compiler-licenses /tmp/qos-release-notices --version 0.1.0 \
  --output /tmp/qos-release-0.1.0
```

The packager checks the staged file inventory, clean source flags, QOS revision,
profile/runtime presence and native deployment targets. It adds release
metadata and dependency notices to a private copy, writes a tarball, checksum,
release metadata and a formula with that exact artifact hash. It never reads
or includes a user disk. The compiler notices are collected from its Cabal
build plan, matching GHC documentation and local package source cache; missing
notices stop packaging. Native shared libraries remain Homebrew dependencies.

The generated formula is published as `Formula/qos-portable.rb` in
`hyperswine/homebrew-tap`. The tarball, `SHA256SUMS` and `release.json` belong
to the QOS GitHub release tagged `desktop-v<version>`. Keep the generated
formula with the release too. Publishing uses GitHub release tools; the
connected GitHub plugin currently has no release upload capability.

## Acceptance and upgrades

Install the generated formula and run `brew test qos-portable`. Run the
[installed SDK acceptance](2026-10-29-DESKTOP-APP-STORAGE.md) against the actual
Cellar prefix, with graphical Main and the prebuilt `tests/sdkdesktop.fpr`
driver. It makes its own project and throwaway external disk, denies checkout
access, excludes GHC/Cabal/make and keeps installed SDK contents read-only.

To qualify a compatible package upgrade, keep that acceptance directory:

```sh
python3 tools/portable-upgrade-check.py prepare --sdk OLD_CELLAR_PREFIX \
  --acceptance /tmp/qos-package-acceptance
# Upgrade the installed package using Homebrew, without launching QOS.
python3 tools/portable-upgrade-check.py verify --sdk NEW_CELLAR_PREFIX \
  --acceptance /tmp/qos-package-acceptance
```

Preparation fingerprints every record and the entire disk with saved count 2.
Verification first requires a different release with the same ABI/API/session
and a byte-identical disk after the package manager upgrade. It rebuilds and
replaces the app using the upgraded compiler/SDK, then the upgraded host loads
count 2 and proves the lifecycle and second-identity checks again. Unrelated
records must remain intact. This checks the package transition actually run;
it does not claim arbitrary future ABI or profile migration.

Projects and writable disks stay outside the Cellar. Formula installation,
upgrade and removal never create or replace a user disk. `qos disk create` is
an explicit one-time operation and refuses an existing path. API/session
incompatibility requires an explicit migration strategy, not reinitialization
of the disk. The initial public API is v2/session 5; generic migration of old
session-4 prototype disks is not implemented.

The final release and upgrade evidence below record the actual package
installation and upgrade; staging alone is not release acceptance.

## Qualification candidate

`desktop-v0.1.0-rc1` was published from QOS `aa50811` with FP-RISC `94f699b`.
The exact tarball installed through `hyperswine/tap/qos-portable`, and its
Homebrew formula test passed. The [installed candidate evidence](evidence/2026-10-29-homebrew-desktop-candidate.json)
records a passing graphical workflow with read-only SDK contents, denied
checkout access, no GHC/Cabal/make, app replacement, restarts and stored state.
The updated prebuilt driver follows Main's colocated storage-service plan;
the [storage guide](2026-10-29-DESKTOP-APP-STORAGE.md) records the earlier
bounded timeout failures and subsequent trials without relaxing deadlines.

Qualification found default Python bytecode caches in the candidate's package
directory. The final release disables those in the helper and both package
wrappers. The prepared upgrade disk contains count 2 and a fingerprint of every
record and the complete disk. The final release record below supersedes that candidate checkpoint.

## Release and upgrade complete

[QOS Portable 0.1.0](https://github.com/hyperswine/qos/releases/tag/desktop-v0.1.0)
is published as the stable release, built from QOS `8afee65` and FP-RISC
`94f699b`. The checksum-pinned formula is published in
[hyperswine/homebrew-tap](https://github.com/hyperswine/homebrew-tap/blob/main/Formula/qos-portable.rb)
at `bfa0d3c`.

```sh
brew install hyperswine/tap/qos-portable
qos new counter
cd counter
fpr build --target=qos-portable
qos disk create "$HOME/qosp.disk"
qos install build/counter.qa "$HOME/qosp.disk"
qos run "$HOME/qosp.disk"
```

The [final package evidence](evidence/2026-10-29-homebrew-desktop-release.json)
records passing Homebrew formula and native dependency checks and the full
graphical installed-SDK acceptance with source access denied. Default formula
commands leave no Python bytecode in the package. Installed SDK contents remain
unchanged during the read-only acceptance.

The [actual package upgrade evidence](evidence/2026-10-29-homebrew-desktop-upgrade.json)
records `brew upgrade` from `0.1.0-rc1` to `0.1.0`: the prepared user disk was
byte-identical after installation and before launch. The upgraded compiler/SDK
rebuilt and replaced the counter as version 1.2.5, and the upgraded runtime
loaded its saved count 2. Unrelated records survived. This qualifies this
compatible package transition, not arbitrary future ABI/profile migrations.

All four workflow slices are complete for this initial macOS ARM64 package.
Other operating systems/architectures, older macOS deployment targets, generic
profile migrations, broader SDK features/assets and physical power-cut testing
remain separate work. The pre-existing live-preferences retention assertion
remains red as documented in the app storage guide; its threshold was not changed.
