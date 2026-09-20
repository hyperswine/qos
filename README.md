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
  The HAL is QOS's; the compiler tree keeps only a machine layer: [docs/HAL.md](docs/HAL.md).
- `Makefile` + `qos-app.mk`: how a program becomes a `.qa`; `qos/Makefile`: the hosts.
- `qos.py`: build, run, disk, bundle, install and release commands.
- `.fpr/` + `fpr.lock`: the committed module versions this tree pins.

QOS Portable is not a Linux program: it builds and runs on FreeBSD/arm64 with
nothing installed in the guest -- see
[tools/freebsd-vm/](tools/freebsd-vm/README.md).

To ship QOS Portable as its own bootable Linux rather than as a program on
somebody else's, see [docs/IMAGE.md](docs/IMAGE.md) and
[tools/buildroot/](tools/buildroot/README.md): a Buildroot image with a
kernel, Mesa, ssh, wifi and `qosp` and nothing else, so a Raspberry Pi 4
powers on into a full-screen FP-RISC application with no window system.

See [the split guide](docs/REPOSITORY-SPLIT.md) for the ownership map and the
release transition.  The previous combined README and tag workflow are kept
under `docs/history/` for reference.
