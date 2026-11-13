# Core builds and packages in Sol

QOS pins FP-RISC `84b0606a2321b720b26438a8bef20df03edf0b11` for these tools.

The contributor build path is `./qbuild`, a Sol script. It builds the compiler,
hosts, process apps and plugins, and packages standalone bundles without Python
or Bash. Make recipes still use POSIX `/bin/sh`; the native C/Haskell toolchains
and platform linkers remain build dependencies. Use released Sol 0.13.1 or a
compatible executable. `qbuild` pins its entry point to 0.13.1; `SOL` can select
a compatible executable for child tools.

```sh
./qbuild build
./qbuild app tests/nativeabi.fpr
./qbuild plugin tests/plugmini.fpr
./qbuild pack tests/nativeabi.fpr --plugin tests/plugmini.fpr --bundle --out /tmp/nativeabi-bundle
/tmp/nativeabi-bundle/run
./qbuild profile --out /tmp/main-profile
```

`app` and `pack` accept a source file or a contributor project directory with
string-valued `[app]` and `[build]` fields in `qos.toml`. `pack` copies project
assets, builds declared or explicit plugins and seeds a fresh bundle disk.
`--bundle` includes a native `run` executable instead of `run.sh`. It selects
the host and optional disk relative to itself and forwards arguments without
shell quoting. Main desktop projects use the installed SDK's native `qos build`.
The legacy source SDK also ships the Sol entry point and a private Sol launcher.
Its packaged hosts are reused rather than rebuilt. The Python contributor
frontend delegates its `build` and `pack` commands to
this Sol implementation; other interactive and test commands may still use Python.

`tools/main-profile.sol` builds Main and its onboard plugins directly from
`profiles/Main.toml`. It uses the compiler's build caches and rebuilds the QA
archives on each invocation. Existing Main disks go through `mkdisk.sol
--preserve`; they are never freshly seeded over user data. `--run` starts Main
without the optional Python compiler daemon. The older `main-profile.py --run`
frontend remains available when that daemon is wanted; its builds delegate to Sol.

## Installed Portable SDK

Build matching hosts and Main before staging. Staging and release packaging
remain Sol commands, and the installed `qos` builder is native:

```sh
make -C qos portable portable-gl
./qbuild profile --out /tmp/main-profile
sol tools/stage-portable-sdk.sol --fprisc ../fprisc --compiler ../fprisc/fpr \
  --profile /tmp/main-profile --output /tmp/qos-sdk
/tmp/qos-sdk/bin/qos new /tmp/counter
(cd /tmp/counter && /tmp/qos-sdk/bin/qos build)
```

For release archives, use `tools/package-portable-sdk.sol` with a clean stage,
version, compiler notices and a fresh output directory. Its existing clean-tree,
matching-revision, inventory, linkage and license checks remain mandatory.
The compiler's `fpr build --target=qos-portable` uses the SDK's native builder,
an explicit executable override, or an explicit Sol override. It no longer
implicitly invokes the retired Python SDK builder.

## Pi compiler SDK

`tools/pi4/compiler-sdk.sol` now builds a compiler/plugin SDK without bundling
or executing Python. From the extracted SDK root, use:

```sh
LD_LIBRARY_PATH="$PWD/lib" bin/sol run.sol check /absolute/source.fpr
LD_LIBRARY_PATH="$PWD/lib" bin/sol run.sol plugin /absolute/source.fpr /tmp/app.qa /tmp/app-build
```

The optional legacy editor daemon is a separate choice: pass
`--python-runtime PREFIX`, containing `bin/python3` and `lib/python3.MINOR`.
The builder copies that target runtime without executing it and records
`compiler_daemon` in `sdk.json`. Omit the option for a Python-free SDK. Building
this Linux AArch64 SDK still requires a native Linux AArch64 host.

## Verification

Local macOS ARM64 checks cover the contributor app/plugin bundle, a native
bundle launch, both native process cell layouts, Main profile generation and
installed Portable SDK staging and acceptance with source checkout access
denied. Native installed desktop and standalone process builds passed with
Python and Bash blocked on PATH. Compact ABI values are 24/6/5; legacy values
are 23/6/4, matching the corresponding preprocessed target headers. QOS's 58
unit tests pass with local process/socket access enabled. A dedicated Linux CI
job builds and runs a bundle with Python and Bash blocked on PATH.

The full sweep still contains Python checks and Bash leg bodies. Runtime compiler
daemons, legacy source SDK installation, ESP-IDF's vendor tools, physical board
qualification and Buildroot's upstream build machinery are separate from these
core build/package entry points. The Pi compiler SDK changes require native
Linux qualification; a macOS staging run does not establish that result.
