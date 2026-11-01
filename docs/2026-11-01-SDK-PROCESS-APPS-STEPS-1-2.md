# `kind = "app"` in the SDK: steps 1 and 2 done

Date: 2026-11-01. This implements steps 1 and 2 of
[SDK-PROCESS-APPS.md](2026-11-01-SDK-PROCESS-APPS.md): the app-side platform
files ship privately in the SDK, `qos build` and `qos run` handle standalone
process apps, and terra-ii and dungeon build from the SDK with no vendored
copy. Overrides (step 3) and the Python-free command (step 4) are not done.
Nothing is released; the next release would be 0.3.0.

## What the SDK ships

`tools/stage-portable-sdk.py` copies 21 files into
`libexec/qos-portable/platform/`, keeping QOS's relative layout where a
file includes another:

| Installed | Source |
|---|---|
| `appside/entry.c`, `hal.c`, `support.c`, `qos_abi.h`, `link-qosapp-a64.ld` | QOS `qos/appside/` |
| `store_abi.h` | QOS `qos/store_abi.h` (`entry.c` includes `../store_abi.h`) |
| `portable/sha256.c`, `loader/qaimg.c`, `hal/net_actor_bridge.c` | QOS |
| `runtime/{runtime,i32,actors,bits,vec,sstr,mod,buddy}.c`, `fpr.h`, `i32.h`, `vec_layout.h` | the FP-RISC tree the compiler comes from |
| `machine/unix/ctx_a64.S` | the same FP-RISC tree |

`sdk.json` gains `platformFiles` (path to SHA-256) and `platformSha256`, one
hash over that inventory. The runtime C comes from the same `--fprisc` tree
as the private compiler (`fpriscRevision`), so a build no longer links one
FP-RISC release's runtime with another's compiler and prelude.
`tools/mkexports.py` is now shipped too. The release packager still refuses
`.c` files anywhere except `platform/`.

`qos/appside/hal.c` now says `#include "net_actor_bridge.c"`; `qos-app.mk`
adds `-I$(HAL)` to the three process-image links, and the SDK adds
`-I platform/hal`.

## `qos.toml` v2

A file with `manifest = 2` is v2. A file without it is v1 and is read by the
unchanged v1 rules.

```toml
manifest = 2

[app]
id = "terra-ii"
name = "Terra II"
version = "1.0.0"
kind = "app"                 # or "desktop"

[build]
entry = "src/terra2.fpr"
target = "qos-portable"
optimize = "checks-only"     # optional; "full" (default) or "checks-only"
compiler-memory-mb = 2048    # optional; a positive number of MiB

[run]                        # optional; kind = "app" only
display = "gl"               # "gl" (runtime/qosp-gl, default) or "none" (runtime/qosp)
disk-mb = 32                 # size of a new data/<id>.disk; default 32
port = 0                     # FPR_PORT for the host; default 0, a free port

[sdk]                        # optional
version = "0.3.0"            # this release or a later one with the same major; "=0.3.0" exactly
```

Unknown tables and keys are refused with the list of valid ones. `[run]` on
a desktop project is refused (a desktop app runs inside Main).

- **`optimize = "checks-only"`** sets `FPR_NO_SPEC`, `INLINE`, `REUSE`,
  `VEC_PEEK`, `VEC_FUSE` and `RECEIVE_TURNS` for the compiler. Type, safety
  and linearity checks stay on.
- **`compiler-memory-mb = N`** sets `GHCRTS=-MNM -A32M`. A v2 build first
  removes any inherited `GHCRTS`, so the user's shell does not change the build.
- **`[sdk] version`** is checked against `sdk.json`'s `release`. A staged
  development SDK has no release; `qos build` then prints one line saying the
  pin is not checked. This is the field `qosmeta` will read to choose an SDK.

## `qos build` for `kind = "app"`

1. Verifies the compiler hash (as for desktop) and every platform file
   against `platformFiles`. A changed file is refused by name.
2. Compiles the entry with the SDK's compiler and prelude, from the project
   folder, with `FPR_HOME=modules` and
   `FPR_PATH=compiler:modules/programs` (so `mods/...` resolves as it does
   for Main). The `.abirev` must equal the SDK's `abi` minor.
3. Compiles the 14 platform units once into
   `$XDG_CACHE_HOME/qos-portable/platform/<key>/` (default `~/.cache`). The
   key hashes `platformSha256`, the SDK path, `clang --version`, the target
   and the flags. The flags are those of terra-ii's `scripts/build.sol`:
   `-O2`, freestanding, x18/x27/x28 fixed, `FPR_POSIX`, `FPR_QOSAPP`,
   `QOS_ARENA_BASE` 1 TiB on macOS (16 GiB elsewhere), `FPR_NHARTS=8`,
   `FPR_SLAB_SZ=262144`, `FPR_STACK_SZ=1048560`. A new key is built in a
   temporary folder and renamed into place.
4. Links with `ld.lld` and the SDK's `link-qosapp-a64.ld` three times: a
   first link that leaves symbols unresolved, `mkexports.py` for the export
   table, then the image at 0 and the check image 256 MiB higher.
5. `mkqa.py --relocatable --check-moved` writes `build/<id>.qa` with
   `loadMode = "process"`, the SDK `abi`, and a build record:
   `sdkPlatformSha256`, `sdkCompilerSha256`, `optimize`, and
   `compilerMemoryMb` and `sdkRelease` when set. The host's manifest parser
   ignores keys it does not know.

`kind = "app"` needs an AArch64 host, because the platform files are the
AArch64 ones. Desktop builds are unchanged.

## `qos run`

`qos run` with no argument, or with a directory, runs that `kind = "app"`
project. `qos run DISK` still runs Main on a disk.

- The image must exist (`qos run` does not build), and its manifest must
  name this project's ID, `loadMode = "process"` and this SDK's `abi`.
- The host (`qosp-gl` or `qosp`) must match `runtimeFiles`.
- `data/<id>.disk` (or `--disk PATH`) is created at `disk-mb` MiB if
  missing, then locked. The host takes over the locked descriptor
  (`FPR_DISK_LOCK_FD`), as for Main.
- `qos run` replaces itself with the host (`exec`), so a test harness that
  stops the process stops the game. `--trace` is passed to the host.

## The two games

terra-ii `597e973` and dungeon `abae8ef` (branch `sdk-app-build` in each):
`support/`, `scripts/build.sol` and `scripts/elf.sol` are deleted (2,150 and
2,140 lines removed). Each has a `qos.toml` v2; terra-ii carries its compiler
settings there instead of in environment variables. `project.sol` runs
`qos build` and `qos run`. The GUI harness starts the game with
`qos run ROOT --disk TMP --trace` instead of a Homebrew path, so the
harness tests whichever SDK is on `PATH`. Their `README.md` and `ORIGIN.md`
say so.

The projects now need Python (the SDK's `qos` command), which they avoided
before. Step 4 of the proposal removes it.

Build times on this Mac with the staged SDK, platform objects already cached:
terra-ii 39 s (compiler peak 557 MB), dungeon 26 s.

## Acceptance

`tools/portable-app-check.py` runs under `sandbox-exec` with the folder
holding the checkouts, both projects, the FP-RISC pin, GHC and Cabal denied,
and the staged SDK read-only. For each project it copies the tracked files
(and refuses a `support/` folder), runs `qos build`, checks the archive's
manifest, and runs the project's own `sol tests/check.sol`. It checks the
SDK did not change, then does the v1 identity check (below), and checks that
a copy of the SDK with one byte added to `hal.c` is refused.

**The v1 identity check holds the SDK's location fixed.** The compiler's
unit order depends on where the SDK is installed: the same compiler and
modules at another path emit the same units in a different order, so the
image differs. SDK 0.2.0 does this too; it is not caused by this change.
Measured: a v1 project built by the 0.2.0 builder and by this builder from
the same staged SDK gives identical bytes (`3889a2b2…`), while the installed
0.2.0 keg gives `f7b2ff28…` for the same project. So the check requires
every desktop input except the builder (`compiler/`, `modules/`,
`support/`, the adapter, `mkimports.py`, `mkqa.py`, `qos_archive.py`, and
the ABI and compiler hash in `sdk.json`) to equal the baseline SDK's, then
builds with this builder and with the baseline's `portable_sdk.py` from one
copy of the staged SDK and requires identical bytes.

```sh
# fprisc-pin at 94f699b; the compiler is the 0.2.0 package's (b20b50c4...)
Q=$(brew --prefix qos-portable)/libexec/qos-portable
python3 tools/stage-portable-sdk.py --fprisc ../fprisc-pin --compiler $Q/compiler/fpr \
  --profile PROFILE_DIR --output STAGE
python3 tools/portable-app-check.py --sdk STAGE --project ../dungeon --project ../terra-ii \
  --baseline /opt/homebrew/opt/qos-portable --fprisc ../fprisc-pin --output OUT
```

PROFILE_DIR held the installed 0.2.0 profile archives, and `qos/qosp`,
`qos/qosp-gl` in this tree are byte-identical to 0.2.0's.

Result, from an SDK staged at QOS `2307391` (clean) and FP-RISC `94f699b`:
passed. dungeon's rule suite and game check and terra-ii's game check pass
inside the sandbox; the v1 check compared 309 desktop inputs with the
installed 0.2.0 keg and got identical bytes from both builders; the
tampered `hal.c` was refused. The desktop acceptance
(`tools/portable-sdk-check.py --gui`, which uses `qos run DISK`) also holds
on the same stage. A dry run of `tools/package-portable-sdk.py` packaged the
stage (with `platform/*.c`) locally, and the packaged copy, which has
`release = "0.3.0"`, accepted `version = "0.3.0"` and refused `"=0.2.0"`
and `"0.4.0"`. See the [evidence](evidence/2026-11-01-sdk-process-apps.json).

## Not done

- Overrides and `c-sources` (step 3). `platformFiles` is the inventory an
  override will be checked against.
- The Python-free `qos` command and a shipped `lld` (step 4).
- `qos new` has no `kind = "app"` template.
- No release, Homebrew formula or tap change.
- Builds are not reproducible across install locations (above). That is a
  compiler matter for FP-RISC (unit order should not depend on paths); it
  matters for `qosmeta`, which installs SDKs under `~/.qos/VERSION`.
