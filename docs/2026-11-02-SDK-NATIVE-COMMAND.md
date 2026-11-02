# A native `qos` and a shipped `ld.lld`: step 4 done

Date: 2026-11-02. This is step 4 of
[SDK-PROCESS-APPS.md](2026-11-01-SDK-PROCESS-APPS.md), after
[steps 1 and 2](2026-11-01-SDK-PROCESS-APPS-STEPS-1-2.md) and
[step 3](2026-11-01-SDK-PLATFORM-OVERRIDES.md). An installed SDK now needs
Clang and nothing else: no Python and no lld on PATH. Nothing is released.

## The command

`tools/qos/` is the command, in FP-RISC:

| File | What it is | Replaces |
|---|---|---|
| `qos.fpr` | the command line, `qos new`, `qos run PROJECT` | `portable_sdk.py` (main, scaffold, run_app) |
| `project.fpr` | `qos.toml` v1 and v2, `[platform]` choices, the SDK pin | `portable_sdk.py` (load, load_v2, platform_choices) |
| `build.fpr` | desktop and `kind = "app"` builds, the platform cache | `portable_sdk.py` (build, build_app) |
| `elf.fpr` | ELF64 images, symbols, relocations; the import stubs and export table | `mkqa.py` (reader), `mkimports.py`, `mkexports.py` |
| `qa.fpr` | QAR2 archives, written and checked | `mkqa.py`, `qos_archive.py` |
| `disk.fpr` | QLOG v3 disks: lock, scan, append, create | `qos_disk.py` |
| `install.fpr` | `qos disk create`, `qos install`, `qos run DISK` | `desktop_install.py` |
| `toml.fpr` | the TOML these files use, read into std/json's Value | `tomllib` |
| `host.c`, `host.fpr` | the host calls std/os lacks | `fcntl`, `os`, `hashlib` |

`host.c` is small and holds no policy. It provides:
- `flock` on a disk opened without close-on-exec, so the host takes over the
  same locked file through `FPR_DISK_LOCK_FD`;
- `setenv` and `unsetenv`, then `Os.exec`;
- `pread`, `pwrite`, `fsync` and `F_FULLFSYNC`, `mkstemp`, `link`, `realpath`
  and `lstat`;
- SHA-256 from QOS's own `qos/portable/sha256.c`, so the command and the
  hosts hash with the same code;
- zero-filled strings, and the offsets where two images differ.

The command reads files and runs Clang, the compiler and the linker through
std/os (`Os.run`). It is built with `fpr build tools/qos/qos.fpr --with
tools/qos/host.c`.

- **Who builds it.** The stager (now `tools/stage-portable-sdk.sol`) builds it with the SDK's
  own compiler and the FP-RISC tree that compiler comes from (`--fprisc`).
  It goes to `libexec/qos-portable/tools/qos`; `bin/qos` is a relative
  symlink to it, and the command finds the SDK from its own resolved path.
- **What the SDK no longer ships.** The SDK has no `.py` file:
  `portable_sdk.py`, `mkqa.py`, `mkimports.py`, `mkexports.py`, `mkdisk.py`,
  `qos_archive.py`, `qos_disk.py` and `desktop_install.py` are gone from it.
  The packager now refuses a `.py` file and checks that `tools/qos` is a
  native binary.
- **The Python builder files stay in this tree.** They are the reference
  that `tools/qos-parity-check.py` and the v1 identity check compare against.

## The stager and packager, in Sol

Later the same day, `tools/stage-portable-sdk.sol` and
`tools/package-portable-sdk.sol` replaced the Python stager and packager,
with shared helpers in `tools/sdk/sdk.sol`. Run them from inside the checkout:

```sh
sol tools/stage-portable-sdk.sol --fprisc ../fprisc-pin --compiler FPR \
  --profile PROFILE --lld LD.LLD --output PREFIX
sol tools/package-portable-sdk.sol --sdk PREFIX --version 0.3.0 \
  --compiler-licenses DIR --output DIR
```

- **Same checks and outputs.** A stage from the Sol stager has the same 342
  files as one from the Python stager, byte for byte, `sdk.json` and the
  inventory included. Both packagers, run on that stage, produced packages
  with the same 378 files and the same formula apart from the tarball's
  hash.
  - Their `sdk.json` and `release.json` are equal as JSON. The only
    textual difference is that Sol's renderer writes a tab in an
    `otool -L` line as `\u0009` where Python's writes `\t`.
  - The tarballs differ as files, because bsdtar and Python's `tarfile`
    write different headers.
  - The packager refuses a stage from another commit, as before.
- **Every file operation is immediate.** That means streams, digest streams,
  and `cp`, `ln`, `chmod`, `find` and `tar` run as processes. One run builds a
  tree and then hashes it; a transactional read of that tree would make Sol
  retry the whole script when the tree changed.
- **Profile archives are checked by the staged command.**
  `qos inspect ARCHIVE --abi ABI [--main]` reads a bundled plugin, or the
  Main entry with `--main`, using the `qos_archive.py` checks, and prints
  `ID SHA256`. It agrees with `qos_archive.py` on all seven 0.2.0 profile
  archives.
- **Two Sol rules the tools follow.**
  - A recursive function, and every caller of one, needs a `: unsafe`
    signature.
  - A lambda's body takes in the following `;` bindings, so blocks go in
    named helpers.

## The linker

Apple's tools cannot link ELF, and the Command Line Tools have no lld.
`tools/build-sdk-lld.sh WORKDIR` builds `ld.lld` and the stager ships it.

- **What the script does.** It sparse-clones `llvm/llvm-project` at the tag
  of Homebrew's llvm (`lld/`, `cmake/` and `libunwind/include`, about 56 MB),
  and builds lld's ELF driver alone. That build links Homebrew's static LLVM
  libraries for AArch64, RISC-V and x86-64; lld's LTO needs their code
  generators.
  - It makes a patched copy of Homebrew's LLVM CMake package: static
    libraries instead of `libLLVM.dylib`, three targets, static zstd, and
    no Z3.
  - It cuts the target `.def` lists that `InitializeAllTargets()` expands.
  - It writes a ten-line `main` that registers only `lld::elf::link`.
- **The result.** LLD 23.1.4, about 96 MB stripped, linking only
  `libSystem`, `libc++` and `libz` from `/usr/lib`, with no rpaths. A first
  build with every target and every lld flavour was 191 MB.
- **Shipping it.** The stager's `--lld PATH` refuses a linker that
  links anything outside the system. It ships it as `toolchain/ld.lld` with
  LLVM's licence (`toolchain/LICENSE-LLVM.txt`, from `packaging/llvm/`). It
  records `toolchainFiles` (the hash) and `toolchainLld` (the version) in
  `sdk.json`; `dependencies` then lists only Clang.
- **Using it.** `qos build` uses `toolchain/ld.lld` when `sdk.json` lists
  it, and refuses a changed one, as it refuses a changed compiler. Without
  one, as with SDK 0.2.0, it uses `ld.lld` from PATH.
- **The formula template.** It drops `python@3.14`, `llvm` and `lld` (lld
  stays only for a package without `toolchain/ld.lld`), links `bin/qos`, and
  lists LLVM's Apache-2.0 with LLVM-exception licence beside MIT.

The proposal says to drive Clang with `-fuse-ld=`. Nothing needs that: the
builder never links through Clang, it runs `ld.lld` itself.

## Evidence

Run from an SDK staged (by the Python stager, before the Sol one replaced it)
at QOS `ef1cfe8` (clean) and FP-RISC `94f699b`, with the
0.2.0 compiler and Main profile and `--lld` from `build-sdk-lld.sh`. See the
[evidence](evidence/2026-11-02-sdk-native-command.json).

- **`tools/qos-parity-check.py`: passed.** For one copy of the SDK, with the
  Python builder copied beside the native one:
  - a v1 desktop app, dungeon and terra-ii built to byte-identical archives
    and printed the same lines. The native builder ran with PATH holding only
    `/usr/bin` and `/bin`, so it used `toolchain/ld.lld`; the Python
    builder used Homebrew's lld 23.1.4.
  - `disk create`, `install` and an update `install` wrote byte-identical
    disks.
  - 20 broken manifests got the same message from both; the other 3 are TOML
    syntax errors, refused by both and worded differently.
- **`tools/portable-app-check.py` (sandboxed): passed.** Checkouts were denied
  and the SDK read-only. The sandbox's PATH held only `clang`, `sol`, `fpr`,
  `cc` and `cat`: no Python and no lld, and the probe asserts both are absent.
  - Both games built with `qos build`, and their own checks ran them with
    `qos run` and passed, PNG snapshots included.
  - The step 3 override cases held: 5 stray copies ignored, an override and
    an added source recorded, the ABI header refused.
  - The tampered `hal.c` was refused.
  - **v1 identity.** 306 desktop inputs equal SDK 0.2.0's. A new v1 project
    built byte-identically by this `qos` with the shipped `ld.lld` and by
    0.2.0's Python builder with Homebrew's lld (`284c50e9...`).
- **`tools/portable-sdk-check.py --gui`: HOLDS.** It ran with no Python and no
  lld on PATH, and with the disk helpers moved into the harness. Covered:
  scaffold, build, `disk create`, `install` and update, graphical Main through
  `qos run DISK`, app-store persistence across app replacement and host
  restart, and the installer's exclusion while a host runs.
  - The first attempt failed with a mismatched driver of mine, built by the
    current FP-RISC (ABI 22.143) instead of the pin's (22.137).

## Not done

- **The acceptance and parity runners are still Python**
  (`portable-app-check.py`, `portable-sdk-check.py`, `qos-parity-check.py`).
  So is the reference builder they compare against.
- **The Python builder files are still in the tree.** Delete them once a
  release has carried the native command and nothing compares against them.
- **Two kinds of build are not reproducible bit for bit.**
  - `ld.lld` rebuilt elsewhere differs in the bytes that record its build
    paths; size, version and behaviour are the same.
  - A `qos build` still depends on the SDK's install location (the
    compiler's unit order; see steps 1 and 2).
- **The toolchain is macOS ARM64 only.** `build-sdk-lld.sh` uses Homebrew
  and macOS tools; a Linux SDK would build lld the same way with that
  distribution's static LLVM.
- **TOML syntax errors are worded differently.** For example, "line 10:
  table [build] is defined twice" instead of `tomllib`'s "Cannot declare
  ('build',) twice (at line 10, column 7)". Every policy message is the same.
- **`qos run DISK` replaces itself with the host,** as `qos run PROJECT`
  does; the Python builder waited for it. The exit status is the host's
  either way.

## Pin policy and reproducibility follow-up (2 November)

The native and reference builders now agree with the managers: compatible
`0.x` pins stay within their minor series; stable pins exclude prereleases;
exact pins include the complete tag. Explicit prerelease pins opt in to tagged
versions and numeric identifiers sort numerically. The installed SDK's next
release must carry this change; manager updates cannot change SDK 0.3.0's
already packaged builder. Development stages without a release number retain
their explicit unchecked-pin warning.

An exact `[sdk] version` pin selects the SDK and its private compiler. It does
not pin host Clang or the system SDK, remove environment overrides, or fix
install/source/output paths. The fixed-path upgrade check is not a hermetic
or cross-machine reproducibility guarantee. The install-location and linker
build-path differences above remain open. See FP-RISC's
[packaging contract corrections](https://github.com/hyperswine/fprisc/blob/main/docs/2026-11-02-PACKAGING-CONTRACT-FIXES.md)
for the shared signing, install recovery and reproducibility contracts.

Native/reference pin parity can be run by building `tools/qos-pin-check.fpr`
with `tools/qos/host.c` and setting `QOS_PIN_TEST_BINARY` when running
`python3 tools/portable-sdk-test.py`. This exercises 20 version combinations,
including prerelease tags, exact pins and incompatible minor upgrades.
