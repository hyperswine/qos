# Installing qos-fpr as a toolchain

`qos-fpr` is one tree with two halves: FP-RISC (the `fpr` binary: the
compiler and the Sol VM) and QOS (the C HAL, the QOS Portable host
`qosp`, the app-side runtime a program is linked with).  The Haskell
half is shipped as a binary.  The QOS half is shipped as *source*
beside a prebuilt `qosp`, because a `.qa` is compiled and linked per
program on the machine that runs it -- the same sources cross-compile
for QEMU virt and QOS Native.

    brew tap hyperswine/tap && brew install qos-fpr      # macOS, Linux
    ./qos.py install --prefix ~/.local                  # from a checkout

Either way you get:

    PREFIX/bin/fpr     -> libexec/qos-fpr/toolchain/fpr     compile | sol | commit | ...
    PREFIX/bin/sol     exec fpr sol "$@"                  the HostedBytecode profile
    PREFIX/bin/qos     -> libexec/qos-fpr/qos.py          run | new | pack | test | ...
    PREFIX/libexec/qos-fpr/
               fpr, core/prelude.fpr, std/, programs/ (mods/ and the
                       examples), sol/ (lib + examples), tools/, tests/,
                       .fpr/ (the committed-version store), compiler/ (source)
        hal/           the C HAL: core (runtime), unix (host tiers), virt
        qos/           qosp, qosp-gl, appside/ (the app runtime + linker
                       scripts), portable/ (the host's source), Makefile
        .installed     the marker: this tree is shipped, never rebuilt

`fpr` and `qos` are *symlinks*, deliberately: the binary finds its
prelude, its std and its store beside its real path
(`compiler/Home.hs`), and `qos.py` finds `` and `qos/` beside
its.  `FPR_HOME=/some/tree` overrides the first; there is no override
for the second because the tree IS the tool.

## The workspace

Nothing you run writes into the installed tree.  Every command writes
to the **workspace**: the directory you invoke it from.

    myapp/
      app.fpr
      .qos/                the workspace (QOS_OUT overrides the location)
        app.qa             the program, compiled and linked for this host
        build/             intermediates (qosapp-prog.s, the elf, plugin .qa's)
        qosp.disk          the host's QLOG disk, when the program opens one
        qos-store/<id>.kv  the app's durable state (its kv log)
      dist/                what `qos pack` produces, one folder per app

`qos clean` removes `.qos/build/` and the `.qa`s and keeps the disk and
the store: those are your app's data, not build output.  From a
checkout, invoked at the repo root, the workspace is `./.qos` and
`./dist`; the Makefiles' own defaults (`build/`, `app.qa`,
`qos/qosp.disk`) are untouched, so `make qos-app PROG=...` and every
`check-all.sh` leg behave as they always did.  `qos.py` is one code
path in both situations -- which is why `install-check.sh` can prove
the installed layout with the checkout's own tests.

## Reaching std from your own project

A program in the tree says `use "../std/mvu"` -- a path relative to the
file, as always.  A project *outside* the tree says

    MV = use "std/mvu".
    U  = use "programs/mods/coreutil".
    B  = use "sol/lib/base".         # in a .sol script

The rule (`compiler/Home.hs`, `Modules.hs`, `Sol/Mod.hs`): a `use` is
resolved relative to the importer first, exactly as before; only a
*miss* is then looked up under the toolchain's home.  A miss in both
places names both:

    use: no such module file: ./nope/missing.fpr  (nor $FPR_HOME/nope/missing.fpr)

The same fallback covers `.fpr/store/<hash>.fpr`: a pinned `use
"x#hash"` resolves from your project's store first, then from the
versions the toolchain was released with.  And `fpr compile in.fpr
out.s` with no `--prelude=` takes `core/prelude.fpr` from home, so the
compiler means the same thing from any directory (`--prelude=` empty
still means none).

`qos new` follows the same split: inside the checkout it scaffolds
under `apps/<name>/` with `use "../../std/..."`; anywhere else
it scaffolds `./<name>/` with `use "std/..."`.

## What each tier needs on the machine

| you run | it needs |
| --- | --- |
| `sol`, `fpr compile` | nothing beyond the install (Linux: mesa's libEGL/libGL, which `fpr` links for Sol's GPU tier) |
| `qos run` (a `.qa` on qosp) | a C compiler: gcc on Linux; on macOS arm64, `llvm` from brew (the app links with `clang --target=aarch64-none-elf -fuse-ld=lld`) |
| `#: host gl` programs | `qosp-gl`, built at install where GLFW's dev package was found |
| `qos run --on virt`, `qos native` | `riscv64-elf-gcc` (+ binutils) and `qemu` |

`qos.py install` reports which hosts it built; a tree without `qosp-gl`
says so the moment a GL program asks for it.

## The formula

`packaging/homebrew/qos-fpr.rb` is the formula; the tap
(`hyperswine/homebrew-tap`) carries a copy that is bumped per release.
It builds `fpr` with ghc + cabal, then runs `./qos.py install --prefix
#{prefix}` -- the same command as above -- so what brew ships is what
`qos/tests-host/install-check.sh` tests: install to a scratch prefix,
then, with only that prefix's `bin` added to PATH and from an empty
directory, `qos new` + `qos run`, `sol` over the installed lib, `fpr
compile` with no flags, `qos pack --bundle` and its `run.sh`, and a
`find -newer` proving nothing under `libexec` was written.

Bottles (the prebuilt path, so users never see ghc) are the tap's job:
its CI runs `brew test-bot` on a macOS arm64 runner and a Linux runner
and attaches the bottles to a GitHub release the formula's `bottle`
block points at.
