# Intended QOS Portable application workflow

Date: 2026-10-28. Kind: intended workflow and implementation plan.
Source baseline: QOS `be701d564212b90866e2ab38a2dbfe0c98b21d68`.

The goal is to develop and use QOS applications with installed binary releases.
An application author should need their own project and a QOS Portable
installation. Building QOS or keeping QOS and FP-RISC source checkouts should
be work for platform contributors, rather than a prerequisite for app authors.

**Update 2026-10-29:** slice 1 is implemented and tested on macOS AArch64.
The [dated update at the end](#update-2026-10-29-slice-1-done-slices-revised)
records what it delivered, which gaps remain, the revised slices and the
decisions needed before slice 2. Everything before that section is the plan
as written on 2026-10-28.

The commands and project manifest below describe the intended interface. They
are not a statement that this interface is implemented. Current source-based
instructions remain in the [repository README](../README.md), and the existing
desktop composition is described in the [Main Profile guide](2026-10-03-GUI-SHELL.md).

## The development loop

```sh
brew install hyperswine/tap/qos-portable

qos new my-qos-app
cd my-qos-app
fpr build --target=qos-portable

qos disk create qosp.disk --profile main
qos install build/my-qos-app.qa qosp.disk
qos run qosp.disk
```

After the shared tap has been configured, the installation can be spelled
`brew install qos-portable`. The compiler executable is currently named `fpr`;
an optional `fprisc` alias can be considered separately.

`qos new` creates a desktop application. The build detects the current host
architecture; the initial workflow supports native builds only. On this Mac,
that means ARM64. No architecture selection or cross-compilation setup should
be needed for the default loop.

`qos disk create` explicitly initializes a writable disk with the Main profile's
initial app set. It refuses to overwrite an existing disk. Disk creation is a
one-time step; later iterations build, install and run against the same disk.
For the first implementation, QOS must be closed before installing. On the next
boot the app appears among the desktop's paged tiles and opens through the
normal shell application interface.

## One installation, separate ownership

The `qos-portable` formula should install the complete app development and
execution environment, using dependencies where appropriate:

| Component | Responsibility |
|---|---|
| FP-RISC binary package | Compiler executable, standard library and required language runtime build inputs |
| QOS SDK | Public QOS modules, trusted-module metadata, pinned dependencies, target support and archive packaging |
| Native build tools | Assembler/linker and supporting tools required by the installed target builder; LLVM/Clang and lld on this Mac |
| Portable runtime | Prebuilt host binaries and graphical dependencies |
| Main profile | Prebuilt matching desktop entry archive, onboard apps and initial disk contents |
| `qos` CLI | Project creation, disk creation, app installation and desktop launch |

The compiler remains owned by FP-RISC; QOS owns its APIs, app adapters, archive
builder and boot profile. One user-facing install command does not require
combining their repositories or duplicating their implementations.

The installed environment must resolve its files through package metadata or
its installation layout, rather than looking for a sibling source checkout.
GHC and Cabal must not be required on an app author's machine. Any Python,
make or other tool retained by the target builder must be supplied or declared
as a dependency, rather than assumed to be present.

LLVM/lld can be installed through Brew. Any retained build step requiring
Apple's SDK must identify the separate Xcode Command Line Tools prerequisite;
the formula must not claim to provide Apple's SDK. Prebuilt hosts and
freestanding app builds should minimize that requirement.

Tools, SDKs and bundled profiles belong in the package installation. Project
sources, build output, writable disks and user data belong outside the Cellar.
Upgrading the formula must not replace a user's disk with a new template.

## Project contract

```text
my-qos-app/
  main.fpr
  qos.toml
  assets/
  .gitignore
  build/                 # generated and ignored
```

A proposed minimal project manifest is:

```toml
[app]
id = "my-qos-app"
name = "My QOS App"
version = "0.1.0"
kind = "desktop"

[build]
entry = "main.fpr"
target = "qos-portable"
```

This is a project configuration proposal, not the existing archive manifest
schema. The builder translates it into the loader's manifest and desktop
metadata. Permissions, resource requirements and asset declarations can extend
the project configuration as their public contracts are defined.

The app ID is stable across updates and must satisfy the existing archive ID
rules. Renaming the source directory or output file must not change the ID or
select a different app's persistent store. Display metadata and archive
identity must come from one source. Architecture, ABI stamps, relocation data
and integrity hashes are generated by the builder.

The builder should discover `qos.toml` in the project. The existing
`fpr build --manifest=...` option concerns compiler cost/target contracts;
it must not silently acquire a second meaning for app configuration.

## Build and SDK integration

The QOS API participates in compilation, linking and packaging. Adding a
manifest around a host executable is insufficient. The target build performs:

1. Resolve the installed, compatible SDK and its pinned module closure.
2. Configure QOS module lookup, foreign declarations and trust metadata before
   import resolution and type checking.
3. Generate the desktop entry adapter and compile the app for the host CPU.
4. Assemble and link using the QOS application support code and the appropriate
   imports, exports and relocation rules.
5. Produce `build/<app-id>.qa`, including the generated manifest, image,
   compatibility information, integrity data and declared assets under an
   explicitly defined asset packaging convention.

The existing ARM64 rules link a freestanding ELF intermediate using Clang/lld.
`tools/mkqa.py` consumes that intermediate and extracts the image into the
[QAR2 archive](2026-07-19-QA-FORMAT.md). ELF is not the runtime archive format,
and a macOS Mach-O executable is not a QOS application image.

QOS should own the installed target builder. `fpr build --target=qos-portable`
can dispatch to it, keeping QOS-specific packaging policy out of the general
POSIX build path. Build tools must use the selected SDK's paths and versions
consistently, including when multiple toolchain versions are installed.

## Desktop application contract

The first supported project type is a Main desktop app. Its public interface
should expose ordinary application state, update, view and subscription/effect
operations. The scaffold and SDK handle the entry adapter and session protocol
so a small app does not have to implement shell bootstrap messages itself.

Main currently attaches cooperative plugins with a root `appMain` export and
a versioned bootstrap/session protocol. Its onboard apps import implementation
modules under `programs/mods/`. An installed SDK needs a documented public
module surface and a supported adapter over that machinery.

There is also an existing `std/hosted` application shape used by programs in
the Editor's panel; see [Programs](2026-10-17-PROGRAMS.md). The SDK design should
reuse its applicable app/effect conventions. That existing panel-hosted path
does not by itself provide installation as an independent Main tile. The first
SDK must choose and test one complete desktop launch path, rather than treating
these two existing interfaces as interchangeable.

Packaging a standalone process or game as `.qa` does not automatically make it
a desktop app. Independent processes, shared graphics and game launch adapters
need their own integration work after the initial desktop path. Existing
cooperative execution boundaries still apply; packaging does not introduce a
new memory or privilege isolation boundary.

## Installing into an append-only disk

`qos install myapp.qa qosp.disk` is an offline QLOG operation. It validates the
archive and publishes its app record and discovery catalogue:

```text
apps/<app-id>.qa
apps/index
```

The app ID comes from the validated manifest, not the archive's filename.
Updating an existing ID publishes its replacement while retaining unrelated
apps and user data. The catalogue contains the installed IDs without duplicate
tiles. The new archive remains authoritative only after successful publication.

Append-only describes QLOG's logical writes. Installation cannot be implemented
by concatenating raw archive bytes onto the backing file. It must respect record
framing, integrity checks, the committed head, DATA/SWAP boundaries and the
[durable QLOG publication and recovery protocol](2026-10-10-PORTABLE-RELIABILITY.md).
The disk has finite capacity, and a full disk requires a clear refusal.

The installer must:

- Validate archive structure, identity, image integrity, architecture, ABI and
  the required desktop entry/protocol compatibility before publication.
- Check capacity before changing committed state.
- Publish archive and catalogue changes in a recoverable sequence. After an
  interruption, the catalogue must refer to complete committed app records;
  an unpublished staged replacement must not become the installed app.
- Preserve existing app records and user data. Replacing an app must not
  implicitly reset its persistent store.
- Acquire exclusive disk access, using a locking protocol also honored by the
  portable host. Refuse a disk already in use.
- Report durable success only after the relevant publication is flushed.

The current `tools/mkdisk.py` seeds or reconstructs an image and has a preserve
mode. It is not yet this transactional offline installer. Multi-record app and
catalogue publication needs an explicit design over QLOG's existing operations;
this document does not assume an existing multi-key transaction primitive.
Live installation through a running QOS storage owner is a later extension.

## Running the disk and managing compatibility

`qos run qosp.disk` selects the installed Main entry archive, launches the
graphical portable host and attaches the requested disk through the host's disk
interface. Main reads `apps/index`, attaches the archives and presents their
tiles. No shell source edit or shell rebuild is needed to add a compatible app.

Initially, the Main entry archive can be shipped beside the host. The writable
disk does not need to contain the boot shell itself. Disk/profile metadata must
record enough information to select or reject an incompatible runtime/profile
combination. Runtime files and the user's writable disk have separate lifecycles.

Host CPU architecture alone is insufficient for compatibility. Release metadata
must cover the compiler/runtime ABI, relevant plane/import contracts and desktop
session protocol as well. Ship and test the host, SDK, Main and onboard apps as
a compatible release set. Installation and launch must report mismatches with
actionable rebuild or runtime-version instructions. An upgrade must preserve
the disk and detect incompatible installed apps instead of launching them
unchecked. The initial policy can require rebuilding affected apps; stable
cross-release app compatibility is a separate commitment.

## Current gaps and implementation order

At the source baseline above:

| Intended interface | Current behavior or missing work |
|---|---|
| `brew install qos-portable` | The shared tap needs a tested binary runtime/SDK release and its compiler/tool dependencies |
| `qos new` and `qos.toml` | A public project scaffold, schema and desktop SDK adapter need to be defined |
| `fpr build --target=qos-portable` | The general build driver uses the POSIX path; QOS has separate application/plugin Makefile rules |
| `qos disk create` | `qos.py disk` currently seeds an image using `mkdisk.py` |
| `qos install app.qa disk` | `qos.py install` currently installs the toolchain under a prefix |
| `qos run disk` | `qos.py run` currently compiles and runs a source program; the host takes an entry archive and a separate disk |

The CLI transition must retain an explicit way to perform existing contributor
operations, or document their replacement, without silently interpreting old
toolchain-install arguments as an app installation.

Implement the path in three slices:

1. Build one external desktop project against an installed SDK into a valid
   `.qa`, with no imports or paths into a source checkout.
2. Create a Main disk, install and update that app safely, then launch the
   prebuilt host and profile and interact with its desktop tile.
3. Publish the compatible binary release set and Homebrew dependencies, and
   prove the complete loop from the installation command.

Acceptance includes building without GHC/Cabal or QOS/FP-RISC checkouts;
opening and interacting with the generated app; replacement without duplicate
tiles or lost user data; preserved state across restarts and package upgrades;
and clear refusal/recovery for malformed archives, incompatible apps, full
disks, concurrent access and interrupted installation. The proposed commands
should become quickstart instructions only after that installed-release path
has passed these checks.

## Update 2026-10-29: slice 1 done, slices revised

### What slice 1 delivered

The [installed desktop SDK v1](2026-10-29-INSTALLED-DESKTOP-SDK.md) is a
staged, read-only prefix that holds the compiler binary, library inputs, the
QOS builder and a prebuilt Main. With it, `qos new` scaffolds a desktop
project, `qos.toml` v1 is parsed strictly, and `fpr build --target=qos-portable`
produces `build/<app-id>.qa`. The archive's manifest records `architecture`,
`desktopSession` and `desktopApi` next to the existing `abi` stamp. The public
module is `qos/desktop` (`qos.desktop/1`).

It was tested on macOS AArch64 with both checkouts sandboxed away and no
GHC, Cabal or make on PATH. The counter opened, updated and closed in
prebuilt Main on a fresh fixture disk. The test builds that disk itself, so
`qos disk create` and `qos install` were not exercised.

The original slice 1 above asked only for the build. The test also covered
opening the app in Main, which removes "launch the prebuilt host" as an open
question for slice 2.

### The gaps table, as of this update

| Intended interface | Status on 2026-10-29 |
|---|---|
| `brew install qos-portable` | Unchanged. The SDK is staged by a contributor tool; there is no release or formula yet |
| `qos new` and `qos.toml` | Done for SDK v1. In the source CLI, `qos.py new NAME` now creates a desktop project in the current directory; `--template min\|service\|mvu\|notes` keeps the old templates under `apps/<name>/` |
| `fpr build --target=qos-portable` | Done. `fpr` hands the build to QOS's `tools/portable_sdk.py` beside the compiler (or `QOS_PORTABLE_BUILDER`). This needs the matching change in FP-RISC's `compiler/Build.hs`, and QOS's FP-RISC pin must include it |
| `qos disk create` | Unchanged |
| `qos install app.qa disk` | Unchanged; the command name is still the toolchain installer |
| `qos run disk` | Unchanged as a CLI command; prebuilt Main with an attached disk is shown to work |

### Persistence is not yet part of the SDK

SDK v1 has no persistent app store. Main plugins share service handles, and
an app ID alone gives neither storage isolation nor persistence. The SDK
counter therefore resets when it closes.

So the acceptance items about preserved user data and state across restarts
and package upgrades cannot be met by SDK apps yet. For slice 2, "user data"
means other apps' archives and existing disk records, which installation must
not disturb. A per-app store bound to the stable ID becomes its own slice.

### Revised slices

1. **Done:** build an external desktop project with an installed SDK and open
   it in prebuilt Main (above).
2. **Disk and install:** `qos disk create` makes a Main disk from the
   prebuilt profile. `qos install` publishes an app and replaces it by ID
   offline, following the installer rules above. `qos run` launches the
   prebuilt host with that disk. Accepted when the SDK counter is installed,
   updated and opened from its tile with no duplicate tile and other apps and
   records unchanged. Malformed or incompatible archives, a full disk and a
   disk in use must be refused. An interrupted install must leave the
   previous app installed.
3. **App storage:** a public API that binds a store to the stable app ID and
   keeps it through replacement. Accepted when an SDK app's state survives a
   restart and an update of that app.
4. **Release:** publish the compatible binary release set and Homebrew
   dependencies, and prove the complete loop from the install command. This
   includes state preserved across a package upgrade. It was slice 3 in the
   original plan.

### Decisions before slice 2

- **The `qos install` name.** It still installs the toolchain under a prefix,
  and the Homebrew formula runs it. Proposal: move that to
  `qos toolchain install --prefix`, change the formula in the same commit,
  and have `qos install --prefix ...` refuse with a pointer to the new
  command, never treating it as an app installation.
- **Commit and pin.** Slice 1 depends on the FP-RISC `Build.hs` dispatch. That
  change has to be committed in FP-RISC and pinned in QOS before the SDK can
  be staged from pinned sources.
- **x86-64.** The builder also selects x86-64, but nothing has tested an SDK
  on that architecture. Until it is tested, slice 2 targets AArch64 only.

## Update 2026-10-29: disk/install milestone complete on macOS AArch64

Slice 2 now implements `qos disk create`, offline manifest-ID installation and
replacement, and `qos run` against the installed prebuilt Main. A shared inode
lock excludes the host and installer, including an inherited lock handoff.
Archive/architecture/ABI/session/entry checks precede publication; app and
catalogue share one durable QLOG bulk-record commit point. A pre-commit
interruption retains the previous app; after the commit point the complete new
app may be visible even if its success acknowledgement was interrupted.

The [disk/install guide](2026-10-29-DESKTOP-DISK-INSTALL.md) records the format,
CLI migration, fault boundaries and focused tests. Installed acceptance denied
checkout/GHC/Cabal access, kept the SDK read-only, preserved unrelated records,
refused installation while Main held the disk, and rendered changed app code.
Physical power-cut qualification and other runtime platforms remain untested.

The old contributor installer moved to `qos toolchain install --prefix`; the
old spelling refuses with an explicit migration hint. The FP-RISC dispatch is
committed and QOS now pins a revision that includes it.

Remaining roadmap: **slice 3, public app storage bound to stable ID**, then
**slice 4, matched binary release/Homebrew packaging and package-upgrade
acceptance preserving app state**. The overall workflow goal remains active.
