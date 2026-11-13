# Replaced-script cleanup (2026-11-13)

This earlier cleanup record is superseded by the [Sol-only main cutover](2026-11-13-SOL-ONLY.md). Its retained-script list describes the earlier checkpoint.

The final pre-cleanup source is preserved in the GitHub release
[`legacy-scripts-final-2026-11-13`](https://github.com/hyperswine/qos/releases/tag/legacy-scripts-final-2026-11-13), including a source archive and checksums.
This is a source checkpoint, not a new binary toolchain version.

Cleanup applies across build, packaging, hardware, tests and tools, but only
where the replacement covers the old behavior. Run the commands below from
the repository root unless indicated. Use `SOL` to select a compatible runtime
in scripts that launch child tools; direct examples use `sol`.

| Removed entry | Replacement |
| --- | --- |
| `check-all.sh` | `sweep --in-place` |
| `models/build.sh` | `cd models; sol build.sol` |
| `tools/build-process-app.sh` | `sol tools/build-process-app.sol` |
| `tools/build-sdk-lld.sh` | `sol tools/build-sdk-lld.sol` |
| `tools/buildroot/board/qosp/rpi4/post-build.sh` | `sol tools/buildroot/board/qosp/rpi4/post-build.sol` |
| `tools/buildroot/board/qosp/star64/post-build.sh` | `sol tools/buildroot/board/qosp/star64/post-build.sol` |
| `tools/buildroot/br.sh` | `sol tools/buildroot/br.sol "$PWD/tools/buildroot" BOARD [MAKE_ARGS]` |
| `tools/pi4/build.sh` | `sol tools/pi4-build.sol QOS_ROOT [OUTPUT]` |
| `tools/pi4/compiler-sdk.py` | `sol tools/pi4/compiler-sdk.sol` |

Historical reports and evidence keep the command names used when they were
recorded. Their old paths are available in the checkpoint release.

## Retained functionality

- `tools/pi4/compiler-sdk-run.py` retains the optional compiler daemon and wire-protocol runtime; the Sol runner covers checks and plugin builds but not that runtime. The default SDK excludes the optional Python runtime.
- `tools/main-profile.py` retains compiler daemon session ownership used by interactive runs and tests. The Sol profile builder alone does not replace that lifetime management.
- `qos.py` and `tools/portable_sdk.py` still support legacy contributor/scaffolding commands and independent SDK comparison tests. Core builds and packaging use `qbuild` and the native SDK builder; the remaining legacy behavior has not been fully ported.
- Shell test legs, disk utilities, runtime services, benchmarks and hardware tools without complete replacements remain. `sweep` is now a pinned Sol entry point; its existing shell test legs are still shell programs.
- Buildroot's upstream Raspberry Pi post-build hook is external vendor functionality and remains in its configuration. Old cached output trees referencing the removed QOSP `.sh` hooks must select the current `.sol` hooks in their `.config`.

The Pi bundle platform guard now lives in `tools/pi4-build.sol`. The SDK linker
builder accepts `WORKDIR` from the repository root, or `DRIVER WORKDIR` explicitly.
The models builder runs from `models/`. The sweep entry runs from the checkout
and keeps its released 0.13.1 bootstrap pin, independent of the compiler under test.

Validation: the pinned Sol sweep listed the QAR2 process group. Native integrity
and ABI refusal tests passed on QEMU with virtio 1 and 2, each with one and two
harts, including real vector-process execution. The production object check
confirmed the test allocation counter is absent. The Pi bundle refused the
macOS host before building; a fresh ARM64 Linux bundle was not built here.
