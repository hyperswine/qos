# Installed desktop SDK v1

Date: 2026-10-29. This implements slice 1 of the
[Portable app workflow](2026-10-28-PORTABLE-APP-WORKFLOW.md).

An installed SDK can scaffold and build an external counter application and
open it in a matching prebuilt Main. Binary release publication, a generic
transactional app installer, and disk/profile upgrades remain later slices.
The tests below use new throwaway disks; they never update an existing disk.

## App author contract

With a staged SDK's `bin` on `PATH`:

```sh
qos new my-counter
cd my-counter
fpr build --target=qos-portable
# build/my-counter.qa
```

`qos build` is also available in this SDK. `-v` shows build details; otherwise
successful builds print the artifact path and retain details in
`build/qos-build.log`. Python 3.11 or newer, Clang and lld must be installed and
available on PATH. GHC, Cabal, make, QOS sources, FP-RISC compiler sources and
Apple framework linking are not part of this app build. The current macOS
proof used Apple's installed Clang as an ELF assembler and Homebrew lld; this
is not a claim that Homebrew or Apple's tools need no installation prerequisites.
This staging step also retains the prebuilt binaries' native library dependencies:
on the tested Mac the compiler uses Homebrew libgit2/libarchive and the graphical
host uses GLFW plus macOS frameworks. Those are installed runtime dependencies,
not bundled by this staging utility; the future release/formula must supply a
matched set.

`qos new` creates `main.fpr`, `qos.toml`, `assets/`, and `.gitignore`. The source
is a module, not an executable requiring a `main`. Its entry adapter is
builder-generated. The minimal configuration is strict: unknown keys and
unsupported project kinds are refused rather than ignored.

```toml
[app]
id = "my-counter"
name = "My Counter"
version = "0.1.0"
kind = "desktop"

[build]
entry = "main.fpr"
target = "qos-portable"
```

- `app.id` is the archive identity and output basename, independent of the
  directory and source filename. It follows the loader's existing 1-64 ASCII
  byte ID rules. Name and version also come from this manifest. The loader's
  line-oriented manifest does not support quoted/backslash-escaped display
  strings; SDK v1 refuses these and control characters explicitly.
- `build.entry` must resolve to a `.fpr` file inside the project. Discovery
  starts in the current directory and walks ancestors for `qos.toml`.
- `assets/` is reserved. Only its scaffold placeholder is accepted for now;
  nonempty assets are refused until runtime asset lookup is specified.
- `fpr build --manifest=...` retains its compiler cost-contract meaning. The
  QOS target refuses that unsupported option; it never interprets it as an
  app project manifest.

## Desktop API and session contract

`D = use "qos/desktop"` is the initial public module. An app provides:

```text
init                         -> (model, List D.Cmd)
update D.Event model         -> (model, List D.Cmd)
view (width, height) model    -> (scene, List String, status)
```

The generated adapter calls the named functions in the app module; it does
not move application callbacks into a trusted SDK loop. It generates the root
`appMain : unsafe Int -> Unit`, negotiates Main's `qos.app-session/4` bootstrap,
validates session/sequence numbers, forwards viewport changes and job results,
and performs bounded close/worker cleanup through the existing `appsession`.
Initial commands and commands returned by the initial Resize are both issued.

Public events are `Key`, `Tick`, `Resize`, `Pointer`, `Wheel`, `Focus`, `Cancel`
and `Arrived`. They are public API data types, converted from Main's nominal
wire types by the adapter. Constructor aliases cannot currently be used in
FP-RISC patterns, so the API does not depend on alias-pattern behavior.
`D.text viewport title subtitle rows` supplies the initial responsive text scene.
`D.Fetch token D.Clock` is the first asynchronous effect; its completion is
`D.Arrived token (Ok (D.Time seconds))` or an error. Main owns the tick source;
there is no per-app subscription scheduler in v1. General jobs, richer public
scene composition and subscription APIs can extend the versioned API later.

This is a cooperative Main plugin, executing in Main's runtime. It does not
create a separate process, memory protection or a new capability boundary.
The Editor's `std/hosted` panel application interface is a different contract.
The SDK library source and its trust metadata are shipped as SDK inputs;
external app sources are not added to the trusted-module allow-list.

## Persistence and compatibility contract

The counter is intentionally session-local: closing and reopening resets it.
Main currently hands plugins shared namespace/storage services. An archive ID
does not create a private plugin store, and this SDK does not expose those
handles as public app storage. A later API must explicitly bind storage keys
and ownership to the stable ID and preserve them through replacement. The
presence of `app.id` here is not a persistence guarantee.

`sdk.json` identifies the OS, native architecture, desktop API/session,
Portable ABI, source revisions, dirty-source flags, compiler hash and tool
dependencies. `files.sha256.json` inventories the staged files for release
verification. The builder rejects SDK/host architecture or API/session mismatch,
a different selected compiler, and compiler hash drift. It ignores inherited
contributor `FPR_HOME`, `FPR_PATH`, `FPR_FOREIGN` and `FPRISC_ROOT` overrides,
resolving modules and trust through the installed SDK only. Builds and Python
bytecode never write into the SDK.

Each archive records the manifest identity, `architecture`, `desktopSession`,
`desktopApi`, and the existing `abi` stamp. The existing ELF/import/relocation
pipeline verifies the moved image before publishing the output file. The
existing loader enforces ABI and the runtime handshake enforces the session.
Architecture/API fields are metadata for the forthcoming installer, not a
new loader validation claim. Ship Main, hosts, libraries and compiler as a
matched release set; native app compatibility across releases is not promised.

## Contributor packaging and acceptance

Build the compiler, hosts and Main once, then stage only binary tools, language
library inputs, packaging helpers and prebuilt runtime/profile artifacts:

```sh
make -C ../fprisc fpr
make -C qos portable portable-gl
python3 tools/main-profile.py --output .qos/sdk-profile
python3 tools/stage-portable-sdk.py --fprisc ../fprisc \
  --profile .qos/sdk-profile --output /tmp/qos-sdk
```

The output prefix must be fresh. The stage tool does not rebuild anything and
does not ship `.git`, Haskell compiler sources, platform C sources or makefiles.
`--profile` is optional for a build-only SDK; runtime acceptance requires it.
Compiler and QOS ownership remain separate even though this staging utility
snapshots the selected compiler and library inputs into one relocatable prefix.
A public formula/release mechanism is still slice 3.

The source-tree CLI also defaults `qos.py new NAME` to this desktop scaffold in
the current directory. Explicit `--template min|service|mvu|notes` retains the
old contributor templates and their existing locations. Existing toolchain
installation via `qos.py install --prefix` remains unchanged; it is not the new
app installer or this staged desktop SDK.

```sh
python3 tools/portable-sdk-test.py
make -s qos-app PROG=tests/sdkdesktop.fpr QA_OUT=/tmp/sdk-driver.qa \
  BUILD=.qos/sdk-driver-build
python3 tools/portable-sdk-check.py --sdk /tmp/qos-sdk \
  --driver /tmp/sdk-driver.qa --output /tmp/sdk-acceptance --gui
```

The macOS acceptance runner blocks filesystem access to both checkouts and the
GHC/Cabal installations using `sandbox-exec`, proves the denial, and provides a
PATH containing only the staged CLI/compiler, Python, Clang and lld. It makes
the SDK read-only and verifies unchanged file hashes afterward. It builds from
a renamed project and renamed entry with spaces in the path and deliberately
supplies stale checkout environment variables. Identity, title, version,
archive image integrity and relocation/import sections are checked.

The prebuilt driver attaches the external archive and uses Main's actual
`appclient` to test opening, two increments, stale-sequence refusal, resize,
reset, bounded close and fresh state on reopening at 1 and 4 harts. A second
external app tests initial clock command delivery and public result conversion. With
`--gui`, prebuilt Main discovers the new tile on a fresh fixture disk, opens it,
renders Count 0 then Count 1, returns home and exits with storage drained.
This needs an active macOS desktop session. The acceptance runner currently
supports macOS; the builder also selects x86-64, whose installed-runtime path
has not yet been validated by this test.

On 2026-10-29 these checks passed on macOS AArch64 with Portable ABI `22.137`
and public API `qos.desktop/1`. Captured frames were visually inspected and
showed Count 0 and Count 1. See the checked-in
[evidence summary](evidence/2026-10-29-installed-desktop-sdk.json).
This is focused installed-SDK evidence, not full CI, Linux/x86-64, Pi deployment,
package upgrade or power-loss installer validation.
