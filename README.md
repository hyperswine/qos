# QOS

QOS is the FP-RISC operating system and Portable application runtime. The compiler
and language libraries live in the sibling `fprisc` repository, selected through
`FPRISC_ROOT` or `fprisc.path`; `fprisc.lock.json` records the qualified source pin.

## Sol-based contributor workflow

From this checkout, with a compatible Sol runtime installed:

```sh
export FPRISC_ROOT=/path/to/fprisc
export FPR_HOME="$PWD"
export FPR_PATH="$FPRISC_ROOT"
./qbuild build host
./qbuild app tests/sol-hello.fpr
./qbuild pack tests/sol-hello.fpr --out dist/hello --bundle
./dist/hello/run
./qbuild profile --out build/profiles/Main
./sweep
```

`qbuild` provides build, app, plugin, profile and pack commands. Bundles use a
native executable launcher. Core builders, archive/disk generation and packaging
are Sol programs under `tools/`; the installed SDK also has a native `qos` CLI.
`SOL` selects the runtime used by child builders. The pinned `qbuild`/`sweep`
launchers use release 0.13.1, independently of the compiler being built.

## Sol-only main

All repository-owned Python and shell script files have been removed from `main`,
including tests, benchmarks, daemon services and extensionless boot hooks. This
is an intentional cutover, not a completed port of every old feature.

[Transition and restoration work](docs/2026-11-13-SOL-ONLY.md) lists the gaps.
The [final legacy source release](https://github.com/hyperswine/qos/releases/tag/legacy-scripts-final-2026-11-13)
preserves the old tools and test suites. Older design documents describe that
historical implementation where they refer to Python/Bash commands.

The current sweep builds the host and a native hello bundle and checks the
Sol-only script policy. It does not run the retired Bash leg manifest or claim
its regression coverage. Compiler-daemon/editor integration and appliance boot
supervision await Sol replacements. Buildroot autostart/splash configurations
fail explicitly while those service implementations are absent.

Native C/Haskell code, FP-RISC application and test fixtures, Makefiles and
upstream vendor toolchains remain. Removing repository scripts does not remove
all external toolchain dependencies.
