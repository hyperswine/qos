# QOS Portable on FreeBSD

FreeBSD/arm64, the server shape: no graphics, no input devices, and **nothing
installed in the guest**. A stock release image runs the binaries as they are.

    tools/freebsd-vm/
      vm.sh            fetch / create / up / down / ssh / put / sysroot
      freebsd-cc       clang, aimed at FreeBSD/arm64, as one word
      server-check.py  drive an FP-RISC server in the guest, from here

## The short answer

It ports. The server side of QOS Portable was already POSIX: `poll(2)`, not
`epoll`; `sigaltstack`/`sigaction`, not `signalfd`; BSD sockets, which are
FreeBSD's own. The Linux-only code is all in the input tiers (`evdev_raw.c`,
`mice_raw.c`), already `#ifdef __linux__` and self-disabling.

One thing genuinely had to change, and it is worth knowing about:

> **A FreeBSD address hint is advisory.** `fpr_heap_reserve` asked for a
> specific address by passing it to `mmap` without `MAP_FIXED` and checking
> what came back — which is exactly right on Linux, where the kernel honours
> a hint when the range is free. FreeBSD quietly returns somewhere else, so
> the check failed at every size and a host whose app images are linked at a
> fixed base could never start. `MAP_FIXED` alone would be wrong: it replaces
> whatever is already mapped. FreeBSD's `MAP_EXCL` turns `MAP_FIXED` into
> "this address or fail", which is the guarantee the hint was standing in
> for. Where `MAP_EXCL` does not exist the old hint-and-check stands, so
> Linux and macOS are untouched. (`fprisc/machine/posix/hal.c`.)

## How it is built

The guest has clang 21 in base, but not `fpr` — that is a Haskell program.
So the build happens on the aarch64 Linux box (`tools/arm64-vm`) and crosses
the **OS, not the architecture**:

    tools/arm64-vm/vm.sh up
    tools/freebsd-vm/vm.sh fetch && vm.sh create && vm.sh up
    tools/freebsd-vm/vm.sh sysroot ~/.cache/qos-freebsd-vm/sysroot

The sysroot is copied out of the running guest, so the headers and libraries
are that exact release's rather than an approximation. Then, in the Linux
guest, with the sysroot beside it:

    export QOS_BSD_SYSROOT=$HOME/freebsd-sysroot QOS_BSD_CLANG=clang-18
    cd qos/qos && make portable \
      QOSP_OUT=/tmp/qosp-freebsd QOSP_ARCH=aarch64 SND_FLAGS= SND_LIBS= \
      FPRBUILD_EXTRA="--cc $HOME/qos/tools/freebsd-vm/freebsd-cc"

`freebsd-cc` is a one-word wrapper because `fpr build --cc` takes a single
token. The same line builds any FP-RISC program — a plain server needs no
`qos/Makefile` at all:

    FPR_HOME=$HOME/fprisc fpr build programs/liveboard.fpr \
      -o /tmp/liveboard-freebsd --cc .../freebsd-cc

**The build machine must already be aarch64.** `fpr` picks the context switch
and `-ffixed-x28` from the machine it runs on, so this crosses the operating
system and the libc, not the instruction set (`fprisc/docs/BOUNDS.md`).

`fpr`'s runtime object cache is keyed by `--cc`, so the FreeBSD objects and
the Linux ones do not collide.

## What it costs

A cross-built `liveboard` or `qosp` is around 400 KB and needs:

    libthr.so.3   libm.so.5   libc.so.7

All three are FreeBSD base. Nothing is installed in the guest — `pkg info`
lists the two packages the release image ships with, and that is the point.

## Checking it

`server-check.py` runs **here**, not in the guest, precisely so the guest can
stay empty. It starts the server over ssh, tunnels the port back (the server
binds `127.0.0.1`, which QEMU's user networking cannot reach, but ssh runs
inside the guest and can), and speaks the page's own websocket protocol:

    tools/freebsd-vm/server-check.py 1000

It asserts the served page, two sessions sharing one model, a delta reaching
both, an event carrying client state, malformed messages refused without
killing the session, a subscription that ticks and stops, a command running
in its own actor, N concurrent sessions all seeing the next update, and the
append-only store written on disk in the guest.

At 1000 concurrent sessions it has run clean repeatedly, which is worth
noting against the Linux figures in `fprisc/docs/LIVE.md`.

## Not done here

Graphics. `qosp-es` needs Mesa's EGL and a DRM device; FreeBSD has both
through ports and `drm-kmod`, but that is a separate exercise and the reason
this tree builds `make portable` rather than `portable-es`.

A native toolchain. GHC is packaged for FreeBSD/arm64 (`ghc-9.10`), so
building `fpr` in the guest and dropping the cross-compilation entirely is
possible — it just is not lean, which was the brief.
