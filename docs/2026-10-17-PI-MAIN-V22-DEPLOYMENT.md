# Pi 4 Main Profile v22 build and deployment

Kind: deployment record, 2026-10-17.

**Status: deployed and accepted on the physical Pi.** Main, the six onboard
apps, ABI 22 host, seed/writable disks and native compiler SDK are installed.
The final normal Main session is ready at PID 13235 and the compiler at PID
517, each with zero automatic restarts. Native Run/Selfhost checks passed on
one and four harts; installed KMS interaction and visual acceptance passed.
The separate 60-second passive health observation also passed with both
service identities unchanged.

## Matching source and artifacts

- QOS base revision: `ed795ea1171381625fe831194e6fd4f1c2ae7331`, plus the
  deployment tooling changes described below, which were uncommitted when
  the deployment artifacts were built.
- FP-RISC: the exact `fprisc.lock.json` pin,
  `905c4f42b143a14976e2170cd9d38f2f487ac16e`.
- Portable ABI: **22**, including the worker-backed compiler bridge from v21
  and host memory reporting for confined run budgets from v22.
- Entry: normal `programs/main.fpr`; no diagnostic Main entry or
  `QOS_BLK_TEST` / `QOS_STORE_TEST` production host flags.
- Onboard applications: `clock`, `logs`, `browser`, `disk`, `terminal`,
  `editor`, from `profiles/Main.toml`. With four built-in shortcuts this is
  ten shortcuts over two pages. The shell, all six archives and host must
  be deployed together because their ABI and shared app-session wire agree.
- Seed: a fresh 32 MiB `Main.disk`. The writable installed disk is upgraded
  separately; replacing the seed alone would not update it.

The production artifacts were built in a native AArch64 Ubuntu 24.04
container, using its GCC and glibc 2.39. The Pi has glibc 2.41; its native
loader preflight resolved every host dependency. No new Buildroot VM was
started. The freestanding AArch64 application images were built on Linux,
with Linux's arena address convention, rather than macOS's different slot
base.

The reproducible build shape inside that Linux environment is:

```sh
export FPRISC_ROOT=/work/fprisc
python3 tools/main-profile.py --force --output /out
make -s -C qos portable-es QOSP_ARCH=aarch64 QOSP_ES_OUT=/out/qosp-es \
  SND_FLAGS=-DQOSP_SND_ALSA SND_LIBS=-lasound
```

The compiler, runtime, generated archives and SDK were taken from the same
source export. `fpr.lock` was refreshed for the new Editor, Terminal and
run-program pinned imports; this does not repin the FP-RISC compiler.

Installed immutable artifact hashes, read back before first startup:

| Artifact | SHA-256 |
|---|---|
| `/usr/bin/qosp` | `c8a092b14b1fa03deea40f17de9c9a8809111b90f540d1cbc88fbc13cf40d34c` |
| `/usr/share/qosp/app.qa` | `3aadb660d82fc6ef4397ef97c3534fc9d796170a725f58c9d24b8487750becdf` |
| `/usr/share/qosp/Main.disk` | `3cf0f92ec12e4c78ce108cb924d2f3455452c5046e3a77d2afae8630f504e377` |
| `/usr/share/qosp/compiler-sdk.tar.gz` | `9aa143cc6c31bd3ba0fcf9eef358804baa9dd334c51b0d7ad41093797a8cc499` |

The six individual archive hashes and tool hashes are in the retained
`bundle/core-manifest.json`; SDK source and compiler provenance are in its
`sdk.json`. Source exports without Git metadata report unknown dirty state,
with explicit base revisions and bundled-source digests.

## Native Editor compiler

The Editor's live checks, Build and Run require a compiler daemon. The
previous appliance session script did not start one; the desktop-only
`tools/main-profile.py --run` wrapper did.

The new [native SDK](../tools/pi4/compiler-sdk.md) installs a compressed
15,439,509-byte archive on the SD card, with 51,692,006 bytes of expanded
regular files. `S98fprd` extracts it onto a bounded
192 MiB tmpfs before `S99qosp`, with a separate 128 MiB tmpfs for compiler
work and caches. The compiler runs locally on the Pi; it requires no build
server or socket forwarding. The existing application supervisor provides
separate compiler process ownership, readiness, bounded shutdown and finite
crash restarts. `/etc/default/qosp` and the installed S99 mechanisms are
preserved.

`EditorCompiler.hs` reuses FP-RISC's existing AOT compiler and source-version
modules without the Sol VM or its graphics/Git/archive dependencies. The SDK
contains private Python, GNU assembler/linker, make and native dependencies;
it is not a general hosted C build environment. `PLUG_A64_LINK` is now
overridable so the standard plugin recipe uses these GNU tools. GHC's live
heap and stack limits are 512 MiB and 64 MiB; the two filesystem quotas bound
extracted files and compiler work separately.

SDK metadata distinguishes the input compiler digest from the packaged
compiler digest after stripping. The latter is
`4d8ec023088e2323dc666c7dae78bf437f0d80ee13427d08171af1bfa2240746`;
the native selftest verifies it against the actual shipped compiler before
compiling. Administrative wrapper shutdown normalizes an expected TERM/INT
result only after the wrapper itself received a stop signal. Unexpected
daemon death retains a nonzero exit, so the supervisor can detect and restart
it. Actual fork/signal tests cover clean stop, startup cancellation and
unexpected child death.

Publication validation exposed a path-based trust issue: Commit copies a
pinned library dependency into a publication's private store, and on the
next check that identical copy shadows the canonically approved shipped
library. `tools/fprd.py` now removes only byte-identical shipped dependency
copies from the private store. Publication roots, edited copies and other
local sources retain their original trust status; the shared SDK store is
never changed or newly approved.

The device's BusyBox tar has no `-z`. Extraction explicitly decompresses to
a temporary tar, checks that gzip succeeded, then extracts and checks tar's
result. Invalid checksums, corrupt gzip/tar and failed stops retain the
previous SDK. The preparation lock and supervisor lock remain separate.

## Installed storage migration and rollback

`tools/pi4/update-main-disk.py` now accepts only the exact standard four-app
or six-app index. It requires all six new archives and appends their records
plus a canonical six-app index, retaining every original committed record
byte, user value and tombstone. Both valid stable v3 superblocks publish the
matching bundle. Custom, reordered, duplicated, incomplete or missing
indexes are refused, as are corrupt/pending disks, exhausted generations and
insufficient capacity.

The installer stopped the old PID 11323 cleanly, took a fresh snapshot and
upgraded the installed writable disk. All 18 original committed records were
preserved byte-for-byte. Head advanced from 3857 to 6383 and generation from
9 to 11; the old four-app index became the six-app index. Both fallback
superblocks replayed the matching six archives and user data.

The writable `/var/lib/qosp/Main.disk` changed from stopped-source SHA-256
`910ad62754c1d21262a5844cc589614108f669d080772aad7c6ca2c0b42f970b`
to installed pre-start SHA-256
`e8c3ff0a07459e07ec9b7356da4770c844d90adbf3ef6bd282eed1dd638981dc`.
This is an installation baseline; the live writable disk may change during
normal use.

The installer checked free SD space, then copied, fsynced and atomically
renamed each destination separately. The two 32 MiB disks were never staged
together on the SD, and the SDK was installed after disk replacement. All
immutable installed hashes matched the production bundle, and the original
configuration/S99 mechanisms passed checksum readback. The first installed
Main PID was 905; the compiler PID was 517. Free root-filesystem space after
installation was 55,880 KiB.

The device-only backup directory is:

```text
/var/lib/qosp/deployment-main-v22-20261017T102722Z/
```

It contains the 3.9 MiB `original.tar.gz`, `original.json`, `original.sha256`,
archive checksum, rollback script and installed manifests. The original
archive SHA-256 is
`be4af7bafd058e12497c1406e2d6bb1915b051076318f297aca6b12a135f9646`.
Installation staging used
`/tmp/qos-main-v22-20261017/install-20261017T102722Z` on the Pi. Original,
stopped and upgraded disk payloads and the rollback archive stayed on the
device throughout this work.

For deliberate rollback, the device retains
`/var/lib/qosp/deployment-main-v22-20261017T102722Z/rollback.sh`.
It verifies the backup, stops the services, restores original files and
restarts old Main. Restoring the old writable disk discards subsequent
writes; preserve a fresh stopped snapshot first if later user data must be
retained. The installer also had an automatic failure path that refused
restoration while live or uncertain process ownership remained.

## Validation completed before installation

Host macOS checks passed with FP-RISC `b4158705155c9fc901d9b2bd3e07e968636d99cc`.
Its delta from the Pi pin concerns printer examples/tests/docs; compiler and
runtime source are identical. The Pi artifacts themselves use the exact pin.

- Real GL integration passed across two boots: six onboard apps, two launcher
  pages, Files/Logs scrolling, launch refusals and reopen/close behavior.
  Terminal wrote/read synthetic text; Editor saved, ran `6 * 7` as `42`,
  rejected a malformed second line and recovered unsaved changes.
- Layout/input passed at 1024x600, 1280x720 and 1920x1080, including touch
  replay, cancellation and keyboard focus. Graphics death and live render
  deadlines drained storage and removed readiness; pane failure/retry passed.
- Guishell, scrolltext and pane MVU contracts passed. Appsession, appjobs,
  appsessionmemory and shelllayout each passed with one and four harts.
- The compiler bridge passed ASan/UBSan checks for a complete 1 MiB reply,
  absent daemon, silent-daemon timeout and abandoned request cleanup.
  Buddy allocation passed 20,000 stress rounds and complete coalescing.
- All 16 disk updater regressions and eight isolated deployment helper tests
  passed. Compiler service tests passed isolation, nested guard ownership,
  RAM quotas, idempotency, checksum/gzip/tar/stop refusal and immutable-store
  publication fallback. Actual wrapper fork/signal tests passed clean stop,
  startup cancellation and preservation of unexpected daemon failure. These
  tests do not mount filesystems or stop QOS.

The host GUI harness's first cold build exceeded its 240-second build timeout
before behavior checks. A resumed run reused artifacts and increased only
harness build timeouts to 600 seconds; all assertions remained intact and no
tracked test source was changed. Its compiler daemon was loaded before the
publication fallback change, so that change is covered by the focused tests
and native SDK selftest, not retroactively by the earlier GUI run.

Physical Pi preflight passed on a Raspberry Pi 4 Model B Rev 1.4:

- The final native SDK selftest checked valid source, produced a 203,386-byte QAR2
  plugin, froze a stable publication, updated it to v1.1 and refused invalid
  source. These requests used the actual local compiler/assembler/linker.
  The final archive and stripped packaged-compiler digest above both passed
  verification.
- An isolated compiler supervisor reached readiness at PID 7708 with zero
  automatic restarts; the installed Main PID remained 11323.
- The private headless GLES Main candidate opened all ten shortcuts and all
  six onboard apps. Terminal created/read synthetic program source. Editor
  compiled and ran it through the Pi's compiler, with a rendered `42` glyph
  match: one changed pixel out of 330, within the eight-pixel tolerance.
  Malformed source was refused at line 2.
- Candidate PID 12866 exited with status zero on clean quit, cleared
  readiness, and left installed Main PID 11323 unchanged. No raw private log
  or framebuffer was exported; only structured acceptance/hash metadata was
  retained.

The original native Run checks failed on both one and four harts because the
test polled and drained console output while expecting the capture to
overflow. A slower Pi producer can be drained every 5 ms without losing any
bytes, so that assertion depended on machine speed. The test now withholds
draining until the root ends, then checks the exact 139,467-byte loss notice
and 65,536-byte retained suffix. This correction changes the test, not the
application or capture implementation. The corrected host checks passed on
one and four harts.

Native program acceptance:

| Case | Result | Elapsed | Peak RSS |
|---|---|---|---|
| Corrected Run, one hart | Pass | 238.534 s | 27,120 KiB |
| Corrected Run, four harts | Pass | 204.950 s | 26,960 KiB |
| Selfhost, one hart | Pass | 34.244 s | 17,276 KiB |
| Selfhost, four harts | Pass | 3.381 s | 17,792 KiB |

The Pi's wall clock initially read January 1970. It was corrected from the
trusted host UTC clock at `2026-10-17 10:16:31 UTC`, without changing NTP
policy or restarting the installed Main process. Existing test output paths
with their original 1970 timestamps remain unchanged.

The original compiler wrapper's administrative stop failure was also
reproduced on the Pi: the child received TERM, the wrapper returned status
241, and the supervisor recorded `failed shutdown-status=241`. After the
correction, the final SDK's isolated S98 start, repeated/idempotent start,
restart and clean stop all passed. The old installed Main stayed at PID
11323 throughout this validation and changed only during the actual install.

## Installed KMS and application acceptance

The installed host ran on V3D through `/dev/dri/card1` with a 1024x600 KMS
scanout. The normal initial Home image was captured before replay. A clean
supervised stop then selected a private on-Pi copy of the installed disk for
input replay; this used the installed binaries and physical KMS at PID 3426,
with zero automatic restarts.

The installed shell reported ten shortcuts across two pages; all six onboard
apps and the built-in Clock were opened. Terminal wrote
and read synthetic source/text, Editor loaded and ran the source through
the local native compiler, and the captured display showed `42`. Malformed
source was refused at line 2. The selected KMS framebuffer captures of Home,
Terminal's synthetic write/read and Editor's `42` were exported as PNGs and
visually inspected. This display evidence supplements the earlier headless
preflight, whose framebuffer stayed on the Pi.

The replay session stopped gracefully, and the normal disk and input
discovery were restored. The original installed writable disk's hash stayed
unchanged throughout replay. Final normal Main PID 13235 was ready with zero
automatic restarts; the compiler remained ready at PID 517 with zero
automatic restarts. Normal Home before and after replay had the same capture
hash. These intentional supervised restarts are separate from automatic
restart counts. Structured acceptance is in `installed-ui/result.json`.

KMS captures prove the pixels selected for HDMI scanout. They do not prove
physical panel/backlight appearance or input delivery from a real keyboard,
mouse or touch controller; input acceptance used replay. No disk payload or
raw private application log was exported. Exported screenshots were limited
to Home, initial application views and synthetic test content.

## Short passive health observation

The passive installed Main/compiler observation passed for 60.00295 seconds
over 13 samples. Main PID 13235 and compiler PID 517 retained the same process
start tokens and readiness throughout, each with zero automatic restarts.

| Measurement | Observed |
|---|---|
| Main RSS | 72,232–72,404 KiB; first-to-last increase 172 KiB |
| Main PSS | 70,768–70,941 KiB; first-to-last 70,771 to 70,940 KiB (+169 KiB) |
| Main CPU | Mean 6.8163% of one core; peak sampled interval 7.1796% |
| CPU frequency | 600 MHz in every sample |
| Temperature | 52.095–53.556°C |

CPU uses monotonic elapsed time and `CLK_TCK=100`; 100% means one fully
occupied core. Raw `/proc` samples remain on the Pi; the exported result is
the bounded JSON summary. This short observation does not establish a
long-duration memory bound or physical power-loss durability.

Raw build logs, host reports, safe JSON summaries and prepared installer
sources are retained under the ignored local evidence directory
`.qos/validation/pi-main-v22-20261017/`. User disk snapshots, raw private
application logs and compressed rollback remain exclusively on the Pi.
The source, tooling and test changes are versioned together with this record.
The deployed artifacts retain the build-time base revisions and source hashes.

Cleanup completed after 60 verification files were copied, flushed and
hash-checked in the backup directory's `verification/` subdirectory.
`final-verification.json` records the installed hashes, healthy service PIDs,
rollback hash and retained evidence hashes. This run's private
`/tmp/qos-main-v22-20261017` tree and the verified-stopped candidate RAM
mounts/control paths were removed. Production
`/run/fpr-sdk/root`, `/run/fpr-sdk-work`, `/run/fprd`, the installed S98
service, configuration, disks and rollback were preserved. Both production
PIDs remained unchanged after cleanup. Final SD free space was 55,552 KiB.
The task's build container was stopped and removed; its saved source and
bundle remain in the local evidence directory.
