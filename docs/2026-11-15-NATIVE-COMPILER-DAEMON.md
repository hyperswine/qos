# Native compiler daemon and the Sol-only Pi SDK

Date: 2026-11-15. Branch `qos-fprd-native`, from `31ade82` (the FP-RISC 0.14.0 pin and the
[candidate record](2026-11-15-PI-FPRISC-0.14.0-CANDIDATE.md)). This does steps 1 to 3 of that
record's migration. Nothing on the Pi changed.

## Step 1: the daemon without Python

`tools/fprd/QosFprd.hs` builds `qos-fprd`, one native program that replaces `tools/fprd.py` and
the Pi SDK's Python runner (`compiler-sdk-run.py`), both retired in the Sol-only cutover.

- **Protocol unchanged.** It is the one `qos/portable/compile.c` speaks: a 0600 Unix socket (a
  path that is not this user's socket is refused, not replaced), 4-byte little-endian frames,
  `"<profile>\n<source>"` requests with whitelisted profiles (`qos-portable`, `bare-metal`,
  `check`, `plugin:<slot>:<id>`, `publication:<id>`, `watch:<id>:<hash>`), and `ok`/`err`
  replies. The 4 MiB request bound, the 30 s frame deadline, the package cache keyed on every
  reachable file's path, mtime and size, the per-module publication writer lock, the
  shipped-dependency cleanup and the registered watches all behave as `fprd.py` did.
- **Each build is a child process** with its own deadline (compiler 120 s, `make plugin-qa`
  300 s) in its own process group, killed whole on expiry or when the daemon stops. A compiler
  crash answers `err`; it does not end the daemon.
- **Same commands as the Pi's installed service.** `qos-fprd daemon --socket --work` and
  `qos-fprd selftest`, so `/usr/libexec/fprd-sdk-session` and `S98fprd` on the device need no
  change. `daemon` writes `$QOSP_READY_FILE` once listening, exits 0 on SIGTERM or SIGINT and
  nonzero otherwise, and removes its socket.
- **Two layouts.** Beside an SDK's `sdk.json` it takes compiler, sources, `make`, `gcc` and
  `sol` from the SDK and sets the environment `run.py` used (`GHCRTS=-M512m -K64m`, the GNU
  plugin link, builds under `--work`). In a checkout it uses `FPRISC_ROOT`, `FPR_HOME` and
  `SOL`, as `fprd.py` did.
- **Build**: `sol tools/fprd/build.sol OUTPUT [FPRISC_ROOT]`. It needs GHC's boot packages and
  `network`; in a cabal-built fprisc checkout it borrows that package environment.
- **Desktop**: `tools/main-profile.sol --run` builds the daemon once and runs it beside
  `qosp-gl` on `$FPRD_SOCK` (default `/tmp/fprd.sock`), stopping it when qosp exits;
  `--no-compiler` (already parsed, never used) skips it. Until now nothing started a daemon
  there, so the Editor could not build on the desktop either.
- The app-side message for a missing server now says `start qos-fprd daemon`.

## Step 2: the SDK packager

- `compiler-sdk.sol --daemon PATH` puts the daemon at `bin/qos-fprd` (it takes the retired
  Python slot through the packaging steps), stages its source, and records
  `compiler_daemon: true` with `daemon_sha256` and `daemon_source_sha256` in `sdk.json`.
  Without `--daemon` the SDK records `compiler_daemon: false` as before.
- The strip step strips into a copy, keeps the mode, and renames it over the original. The
  in-place `strip` failed with "Text file busy" because one of the binaries is the Sol runner
  doing the packaging.
- The leftover Python standard-library step is gone.

## Step 3: the builder

`debian:trixie` (glibc 2.41, equal to the Pi's) with FP-RISC CI's package list plus
`clang lld llvm`, recorded in [tools/pi4/compiler-sdk.md](../tools/pi4/compiler-sdk.md).

## Checks

| Check | Result |
|---|---|
| `qos-fprd selftest` on macOS arm64, checkout layout, fprisc main | check ok; plugin QAR2, 203,597 bytes; publication committed, frozen, stable, updated to v1.1; invalid source refused |
| Daemon on macOS: a regular file at the socket path | refused, exit 1 |
| Daemon on macOS: readiness file, socket mode, SIGTERM | pid written, 0600, exit 0, socket removed |
| `debian:trixie` arm64: build `qos-fprd`, package the SDK with the 0.14.0 Editor compiler (`566870c3`) | built; archive 39,033,395 bytes (under the 40 MiB limit by 2.6 MB) |
| The extracted SDK's `bin/qos-fprd selftest` in that container | same results as on macOS, compiler digest matches `sdk.json` |
| `tools/sol-only-check.sol` | passed |

Not checked: the daemon on the Pi itself, the Editor building through it inside qosp, and the
SDK unpacked into the device's RAM filesystems.

## Still to do (steps 4 to 10 of the candidate record)

Rebuild the bundle from clean exports of the pinned pair (now including this SDK), replace the
Python qualification drivers, migrate the writable disk off the device, add the SDK, its hash,
the `fprd` stop and start and a daemon probe to `install.sh`, install with rollback, then verify
on the device (installed hashes, soak, HDMI readback, an Editor build of a small program).
The SDK archive is close to its 40 MiB bound.
