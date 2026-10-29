# QOS

QOS Native, QOS Portable, their HAL and services, the QOS programs written in
FP-RISC, and the `qos.py` driver.  The compiler, runtime and language libraries
are developed in the separate [fprisc](https://github.com/hyperswine/fprisc)
repository; this tree only needs to know where a checkout of it is.

```sh
git clone https://github.com/hyperswine/fprisc ../fprisc   # a sibling needs no setup
./qos.py fprisc ~/wherever/fprisc                          # or say where it is, once
./qos.py build
./qos.py run tests/hello.fpr
./qos.py run programs/interactive_desktop_gl.fpr
```

The [intended installed-release app workflow](docs/2026-10-28-PORTABLE-APP-WORKFLOW.md)
tracks the installed SDK, external projects, QOS-target builds, disk
installation, desktop launch and persistent app state. These slices are
implemented on macOS ARM64. The [binary package guide](docs/2026-10-29-DESKTOP-RELEASE.md)
records the published macOS 27+ ARM64 package and upgrade acceptance. Install
it with `brew install hyperswine/tap/qos-portable`; the source contributor
quickstart remains below.

## Quickstart

Checked on Debian trixie x86-64, using GHC 9.8.2 and cabal 3.12 from ghcup. macOS was not re-checked for this section.

Prerequisites: GHC and cabal (via [ghcup](https://www.haskell.org/ghcup/)),
Python 3, make, a C compiler, and the development packages that fprisc needs
(libgit2 >= 1.9, which Ubuntu 24.04 does not ship, so use Debian trixie or Homebrew):

```sh
sudo apt-get install make gcc pkg-config python3 libgit2-dev libarchive-dev \
  libegl-dev libgl-dev libgmp-dev zlib1g-dev
```

Build the compiler in a sibling checkout, then QOS Portable, then run hello:

```sh
git clone https://github.com/hyperswine/fprisc ../fprisc
make -C ../fprisc fpr          # first build fetches Haskell deps; takes a while
./qos.py fprisc                # shows which fprisc checkout is used
./qos.py build
./qos.py run tests/hello.fpr   # [qos] hello => hello from a .qa: fold(1..10)=55 clamp=55
```

Tests (what CI's host job runs):

```sh
./qos.py lock --check
python3 -m unittest discover -s tests -p 'test_*.py'
./qos.py test hello            # one smoke leg; `./qos.py test --all` is the full local sweep
```

`./qos.py run` warns when `../fprisc` is not at the release pin in
`fprisc.lock.json`. CI builds the pinned revision.

## App loop today: install, new, run, pack

This loop works today against an installed toolchain, outside any checkout and with no GHC
or cabal on PATH. It was checked on Debian trixie x86-64 (2026-10-29), with the checkouts
moved out of sight. **The install must be built from a qos and fprisc
checkout on the same machine** (the Quickstart above, once). No binary release or Homebrew
formula exists yet.

```sh
./qos.py toolchain install --prefix ~/qos-sdk        # from the checkout; copies a relocatable toolchain
export PATH="$HOME/qos-sdk/bin:$PATH"      # qos, fpr, sol
cd ~/src                                   # anywhere outside the checkout
qos new hello --template mvu               # standalone app.fpr; desktop is the default template
qos run hello/app.fpr                      # [qos] app => hello: done count=12 note=hi ...
qos pack hello/app.fpr --bundle            # dist/hello/{hello.qa,qosp,run.sh}
dist/hello/run.sh                          # the bundle runs on its own
```

At run time an app still needs make, a C compiler and python3, because each `qos run`
compiles the app's C support code and links it. Build output goes to `.qos/` and `dist/`
in the directory you run from.

For the separate Main desktop app path, the staged installed desktop SDK
has been validated on macOS AArch64; see the
[desktop SDK guide](docs/2026-10-29-INSTALLED-DESKTOP-SDK.md). Its default
`qos new` scaffold uses `main.fpr` and the generated Main session adapter.

Not verified for the standalone loop above: macOS, and GL host apps (`#: host gl`,
qosp-gl), which need GLFW at install time. The separate desktop SDK supports
offline tile installation/replacement and persistent app state; see the
[workflow milestones](docs/2026-10-28-PORTABLE-APP-WORKFLOW.md).

Try the graphical Main Profile shell with its onboard apps:

```sh
python3 tools/main-profile.py --run
```

It opens a paged shortcut grid. Click or use arrows and Enter to open; Escape
returns home, Page Up/Down changes pages, and Q exits from home. See the
[Main Profile guide](docs/2026-10-03-GUI-SHELL.md) for boot-image wiring and
the current prototype's application contract. The run also starts the host
compiler daemon, so the Editor app can build FP-RISC (^B) and run it as a
process of its own (^R): [docs/2026-10-16-EDITOR.md](docs/2026-10-16-EDITOR.md).
A run is given a memory budget and is not granted the devices, and a program
can be an app in the Elm shape (`std/hosted`) that draws in the Editor's panel
and reads and writes `/home` through it:
[docs/2026-10-17-PROGRAMS.md](docs/2026-10-17-PROGRAMS.md).
That isolation is cooperative, not enforced: QOS has no MMU or privilege
boundary between programs (every process runs in M-mode on Native, and in
the host's address space on Portable), and each process checks its own
grants. Native code in a `.qa` can ignore them, so only run programs you
trust.

QOS Portable also runs on Linux riscv64. The [STAR64 implementation and
hardware record](docs/2026-10-14-STAR64-PORTABLE.md) covers RV64 cross-builds,
Main's HDMI/keyboard setup and the faster LLVMpipe software renderer.

One path names the fprisc checkout, found in this order: `--fprisc DIR` on an
invocation, `$FPRISC_ROOT` in the shell, `fprisc.path` in this tree (what
`./qos.py fprisc DIR` writes; it is ignored by git), then a sibling `../fprisc`.
`make` run directly applies the same order (`dependency.mk`).  Nothing is
copied, linked or generated into either checkout; `./qos.py fprisc` prints
what was found and where.  `./qos.py fprisc --pin` records the clean compiler
commit in `fprisc.lock.json` for releases.

- `programs/`: the QOS kernel, services (`programs/mods/`) and examples.
- `apps/`, `models/`, `std/`, `tests/`, `tools/`: applications, meshes and
  music, QOS-side library modules, integration checks, packaging tools.
- `qos/`: the portable host, native entry, application-side HAL and host checks.
- `hal/virt/`: the QOS HAL on the virt board -- the PLIC, virtio net and block, the pin bus.
- `hal/unix/`: the QOS HAL over a Unix host -- graphics, audio, input, net, block, tty.
- `loader/`: QOS application, process and image loaders (the kernel's side of launching).
  The HAL is QOS's; the compiler tree keeps only a machine layer: [docs/2026-09-19-HAL.md](docs/2026-09-19-HAL.md).
- `Makefile` + `qos-app.mk`: how a program becomes a `.qa`; `qos/Makefile`: the hosts.
- `qos.py`: build, run, disk, bundle, install and release commands.
- `.fpr/` + `fpr.lock`: the committed module versions this tree pins.

QOS Portable is not a Linux program: it builds and runs on FreeBSD/arm64 with
nothing installed in the guest -- see
[tools/freebsd-vm/](tools/freebsd-vm/README.md).

To ship QOS Portable as its own bootable Linux rather than as a program on
somebody else's, see [docs/2026-09-21-IMAGE.md](docs/2026-09-21-IMAGE.md) and
[tools/buildroot/](tools/buildroot/README.md): a Buildroot image with a
kernel, Mesa, ssh, wifi and `qosp` and nothing else, so a Raspberry Pi 4
powers on into a full-screen FP-RISC application with no window system.

The [chronological documentation index](docs/README.md) separates dated designs,
implementation records, references and later updates.

See [the split guide](docs/2026-09-18-REPOSITORY-SPLIT.md) for the ownership map and the
release transition.  The previous combined README and tag workflow are kept
under `docs/history/` for reference.

The first installed-app slice is available for contributor staging: see the
[installed desktop SDK v1 guide](docs/2026-10-29-INSTALLED-DESKTOP-SDK.md). It builds
an external counter with a read-only SDK and no source checkouts or GHC/Cabal.
Safe app updates and [stable-ID app storage](docs/2026-10-29-DESKTOP-APP-STORAGE.md)
are implemented; [binary package qualification](docs/2026-10-29-DESKTOP-RELEASE.md)
completes the four revised roadmap slices on macOS ARM64.

The installed AArch64 Main disk workflow now supports `qos disk create`,
`qos install APP.qa DISK`, and `qos run DISK`, with offline locking and atomic
app/catalogue publication. See the [disk installation guide](docs/2026-10-29-DESKTOP-DISK-INSTALL.md).
The contributor toolchain installer is `qos.py toolchain install --prefix DIR`.
