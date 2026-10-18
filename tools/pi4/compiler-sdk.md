# Native Editor compiler SDK

The Pi runs the Editor's existing compiler daemon locally. Its compiler and
assembly tools come from a compressed SDK on the SD card; boot extracts them
into a bounded RAM filesystem. Compilation and caches use a second bounded RAM
filesystem. No build server or forwarded socket is required after deployment.

Build the Editor entrypoint inside the same native AArch64 Linux container as
the compiler, using the pinned compiler's modules and existing build objects:

```sh
cd /work/fprisc/compiler
ghc -O0 -threaded -rtsopts -with-rtsopts=-V0.001 -i. -main-is PiEditorCompiler \
  -o /out/fpr-editor /work/qos/tools/pi4/EditorCompiler.hs
```

Then package and exercise the SDK:

```sh
python3 tools/pi4/compiler-sdk.py --qos /work/qos --fprisc /work/fprisc \
  --compiler /out/fpr-editor --compiler-kind editor --output /out/compiler-sdk.tar.gz \
  --qos-revision "$QOS_REVISION" --fprisc-revision "$FPRISC_REVISION"
mkdir /tmp/compiler-sdk-check
gzip -dc /out/compiler-sdk.tar.gz > /tmp/compiler-sdk.tar
tar xf /tmp/compiler-sdk.tar -C /tmp/compiler-sdk-check
rm /tmp/compiler-sdk.tar
/tmp/compiler-sdk-check/bin/qos-fprd selftest
```

Set the revision variables to the exact source-export revisions recorded by
the appliance build. The packager requires make, GCC, binutils, Python and the compiler's dynamic
libraries to be installed in the build container. It strips ELF objects,
packages Python's standard library in a zip, follows native library
dependencies, and refuses an archive larger than 40 MiB. The manifest records
source revisions, dirty state, input and packaged compiler digests, bundled-source digest, Python
version and build glibc. It records the Editor entrypoint's source digest too.
Source exports without `.git` require explicit
`--qos-revision` and `--fprisc-revision` arguments; their dirty state is unknown.
Pinned source blobs and version metadata are included for older module pins.
The bundle carries no glibc or dynamic loader: the Pi's glibc must be at least
as new as the build container's. Ubuntu 24.04's 2.39 can run on this Pi's 2.41.

`EditorCompiler.hs` links the existing `Compile` and `Commit` modules without
the Sol VM and its graphics, Git and archive libraries. It supports AOT
`compile`, `commit`, `versions`, the daemon's direct compile arguments, and
`--version`. It does not replace the full compiler in the production builder.
All daemon check, plugin, publication and registered-watch operations use
these existing frontend/commit APIs.

Plugin generation uses the standard `plugin-qa-a64` make target with an
overridden `PLUG_A64_LINK`. Native GCC assembles the generated `.s` files and
links them with GNU ld. There is no C frontend, C header tree, LLVM, or Clang in
the SDK. This supports the Editor's front-end checks and relocatable QOS
plugins; it is not a general C or FP-RISC hosted executable build environment.

The selftest talks to a real daemon over its Unix socket. It checks valid
source, builds a QAR2 plugin through compiler/assembler/linker/packaging, and
commits/freezes a stable publication, updates its version, and verifies that invalid source is
refused. It does not claim that qosp loaded
the resulting plugin; that requires the separate application/device test.

Deploy these matching files with the appliance update:

| Source | Pi location |
| --- | --- |
| `compiler-sdk.tar.gz` | `/usr/share/qosp/compiler-sdk.tar.gz` |
| `compiler-sdk.tar.gz.sha256` | `/usr/share/qosp/compiler-sdk.tar.gz.sha256` |
| `tools/pi4/S98fprd` | `/etc/init.d/S98fprd` (0755) |
| `tools/pi4/fprd-sdk-session` | `/usr/libexec/fprd-sdk-session` (0755) |

`S98fprd` starts before `S99qosp`. The shell's default compiler socket is
`/tmp/fprd.sock`; a custom `FPRD_SOCK` must also be exported by the qosp session.
The compiler service reuses the installed QOS guard and supervisor with its
own `/run/fprd` ownership, readiness, log and process group. It allows three
crash restarts with finite backoff and requires explicit restart after the
budget is exhausted. It never owns or writes Main's disk. Commands are:

```sh
/etc/init.d/S98fprd start
/etc/init.d/S98fprd status
/etc/init.d/S98fprd restart
/etc/init.d/S98fprd stop
```

Optional `/etc/default/fprd` settings are `FPRD_ARCHIVE`, `FPRD_SDK_RAM`,
`FPRD_SDK_ROOT`, `FPRD_WORK`, `FPRD_SOCK`, `FPRD_SDK_SIZE` (default 192m),
and `FPRD_WORK_SIZE` (default 128m). Both RAM paths must be under `/run` or
`/tmp`. The service refuses to spill its unpacked files or caches onto SD if
mounting tmpfs fails. Build requests retain the daemon's existing source and
wall-time limits, with a 512 MiB GHC live-heap cap and 64 MiB Haskell stack cap;
exhaustion of the bounded work filesystem is a build error.
All caches and unpersisted publication history disappear at reboot. The
Editor persists chosen source/packages in QOS storage as before.

Before checking a publication again, the daemon removes only private dependency
copies that exactly match a shipped source blob. This lets normal resolution
use the original SDK source, whose canonical path carries the platform's
explicit library approval. Private publication roots and edited blobs remain
local. No shared source is overwritten or newly granted approval by this step.
