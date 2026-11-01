# Proposal: standalone apps in the SDK, with the app-side HAL hidden

Status: proposal, 1 November 2026. Nothing here is shipped. It goes with
FP-RISC `docs/2026-11-01-TOOLCHAIN-MANAGER.md`, which proposes installing SDK
versions side by side under `~/.fpr/qos-portable/VERSION`.

## The problem

`qos build` (SDK v2, `tools/portable_sdk.py`) builds exactly one kind of
project: `kind = "desktop"`. That is a windowed plugin that Main hosts,
linked with `support/link-qosplug.ld` behind the generated desktop adapter.
Anything else is refused.

terra-ii and dungeon are a different kind of app. Each is a full-screen 3D
program that `runtime/qosp-gl` runs directly as its own process image
(`--target=qa64`, own entry point). To build them outside the QOS repo, each
project carries:

- **`support/`.** Nine files, 1,933 lines, identical in both projects and
  byte-identical to QOS `main`'s `qos/appside/`:
  - `qos/appside/entry.c`, `hal.c`, `support.c`, `qos_abi.h` and
    `link-qosapp-a64.ld`;
  - `qos/store_abi.h`, `qos/portable/sha256.c` and `loader/qaimg.c`;
  - `hal/net_actor_bridge.c`. The `support/hal/` folder exists only because
    `hal.c` includes `../../hal/net_actor_bridge.c` by relative path, so the
    projects copy QOS's directory layout to satisfy that one line.
- **`scripts/`.** About 270 lines of Sol per project, identical apart from
  names:
  - the Clang/lld command line with the runtime's `-D` build settings
    (`FPR_NHARTS=8`, slab and stack sizes, `QOS_ARENA_BASE`, fixed x18, x27
    and x28);
  - a two-pass link that builds the export table;
  - a third link moved by 256 MiB, to check relocations;
  - an ELF/QAR2 archive writer.
- **Homebrew paths.** The scripts call `brew --prefix` for `fprisc`,
  `qos-portable`, `llvm` and `lld`.

### Two releases mixed in one build

The build mixes two releases. It compiles with the FP-RISC 0.12.0 formula's
`fpr` and links that formula's runtime C files (`runtime.c`, `actors.c`,
`ctx_a64.S` and the rest; FP-RISC `eb7edcf`). But it uses the QOS SDK's
prelude and modules (FP-RISC `94f699b`). The SDK's private, hash-matched
compiler, which exists to prevent exactly this, is bypassed.

The only guard is `build/app.s.abirev` equal to the SDK's `abi` minor. That
is `codegenRev`, 137 in both compilers today. So the build works because the
two releases happen to share a code-generation revision, not because anything
checks that the runtime C, prelude and modules belong together. The next
FP-RISC release that changes the runtime without bumping `codegenRev` would
link silently and misbehave.

## Proposal

### 1. A second project kind: `kind = "app"`

This needs `qos.toml` v2. v1 refuses unknown keys, so v2 is a new format
number; v1 files keep building as they do now.

```toml
manifest = 2

[app]
id = "terra-ii"
name = "Terra II"
version = "1.0.0"
kind = "app"            # "desktop" (today's plugin) or "app" (standalone process image)

[build]
entry = "src/terra2.fpr"
target = "qos-portable"

[run]
display = "gl"          # runtime/qosp-gl; "none" for runtime/qosp
disk-mb = 32            # data/<id>.disk, created by `qos run` if missing

[sdk]
version = "0.3.0"       # oldest compatible SDK; read by the toolchain manager
```

For `kind = "app"`:

- `qos build` compiles the entry point with the SDK's own compiler and
  prelude.
- It links the app-side files and the runtime from inside the SDK, with the
  SDK's linker script and build settings.
- It does the export-table link and the 256 MiB relocation check.
- It writes `build/<id>.qa` with `loadMode = "process"` and the SDK's
  `abi`.

`qos run` creates the project's data disk if needed and starts the host
named by `display`. terra-ii's `project.sol` does all of this by hand today.

Everything comes from one SDK revision, so the mixed-release problem goes
away. The compiler, prelude, runtime C, app-side files and linker script are
hashed together in `sdk.json`, as the compiler already is.

### 2. Platform files are the SDK's private build inputs

- **What the SDK ships.** The app-side files, the loader, `sha256.c`, the
  runtime sources and the linker scripts, in a private folder such as
  `libexec/qos-portable/platform/`. This is not a public interface.
- **How they are compiled.** Into the user's cache, keyed by the SDK hash,
  target and build settings, the same way `fpr build` caches C objects.
  Shipping prebuilt `.o` files is an optimisation for later; the right
  settings would first need to be fixed as a contract.
- **What a project contains.** `qos.toml` and its `.fpr` sources, nothing
  more. A project never has a copy of `hal.c`.
- **The include path.** The relative include `../../hal/net_actor_bridge.c`
  becomes an ordinary `#include "net_actor_bridge.c"` resolved by `-I`
  inside the SDK. No project mirrors QOS's folder layout again.

### 3. Overriding a file, only on purpose

Someone who wants their own HAL or entry code names the replacement in the
manifest:

```toml
[platform.override]
"appside/hal.c" = "native/my_hal.c"     # replaces the SDK's file of that name

[platform]
c-sources = ["native/sensor_bridge.c"]  # extra C linked into the image
```

- **Only listed files.** Only names listed in `sdk.json`'s platform inventory
  can be overridden. An unknown name is an error that lists the valid ones.
- **The ABI header stays.** Overrides still compile against the SDK's
  `qos_abi.h`, `store_abi.h` and `fpr.h`. Those headers are the ABI, so
  overriding them is not allowed. A program that needs a different ABI needs
  a different SDK.
- **Overrides are recorded.** The archive manifest lists each overridden or
  added file with its hash, under `platformOverrides`. `qos build` prints one
  line per override, and the disk installer shows them. A replaced HAL is
  visible, never a surprise.
- **No automatic shadowing.** A `platform/hal.c` that merely sits in the
  project does not win. Shadowing by search path is how a stale copy takes
  over silently. terra-ii's and dungeon's `support/` copies are exactly such
  copies: correct today, wrong after the next SDK. Overriding takes one
  explicit line.

### 4. No Python, and `lld` shipped

- **No Python.** The SDK's `qos` command is a Python script, and its archive
  writer is `tools/mkqa.py`. terra-ii already contains an ELF/QAR2 writer in
  Sol (`scripts/elf.sol`) that needs no Python, objcopy or readelf. That
  shows the SDK's command and packager can be rewritten in Sol or FP-RISC
  and shipped as a binary. The Python requirement then goes, and the
  toolchain manager can install a QOS SDK as easily as an FP-RISC
  toolchain.
- **`lld` shipped.** Apple's tools cannot link ELF. So the SDK ships
  `ld.lld` (statically linked; LLVM's licence permits it) and drives Clang
  with `-fuse-ld=` pointing at it. Checked: Apple Clang 21 from the Command Line
  Tools compiles for `aarch64-none-elf`. The Command Line Tools have no
  `lld`, which is why the SDK has to ship it. Homebrew `llvm` would then no longer be needed.

### 5. Compiler settings for large programs

terra-ii lowers the compiler's memory use and turns off optional optimisations
(`GHCRTS=-M2048M -A32M`, `FPR_NO_SPEC`, `FPR_NO_INLINE` and four more)
through environment variables. The manifest should carry this as a
documented setting, for example `[build] optimize = "checks-only"` and
`compiler-memory-mb = 2048`. The archive records it, so the build can be
repeated, and environment variables are never the interface.

## Migration

Moving terra-ii and dungeon over takes three steps:

1. Delete `support/` and `scripts/elf.sol`, `scripts/build.sol`.
2. Add a `qos.toml` v2 like the one above.
3. Change `project.sol build/run` to call `qos build` and `qos run`, or drop
   it for those commands. `project.sol test` can stay as their own test
   runner.

## Acceptance

Run under the existing sandbox profile, with checkouts denied and the SDK
read-only:

1. terra-ii and dungeon, with no `support/` folder, build with `qos build`
   and run with `qos run`. Their game checks pass and their screenshots
   match.
2. A copy of the SDK with `hal.c` changed in one byte gets a different SDK
   hash. A project built against it records the new hash.
3. An override of `appside/hal.c` builds, prints its line, and is listed in
   the archive. An override of `qos_abi.h` is refused.
4. A stray `platform/hal.c` in a project without an override line changes
   nothing: the output is byte-identical to a build without it.
5. A `kind = "desktop"` v1 project still builds byte-identically to SDK
   0.2.0.

## Order of work

1. Ship the platform files privately in the SDK, and add `kind = "app"` to
   the current Python builder.
2. Migrate terra-ii and dungeon. This removes the mixed-release build now.
3. Overrides and `c-sources`.
4. Rewrite the command and packager in Sol or FP-RISC, and ship `lld`. This
   is what the toolchain manager needs.
