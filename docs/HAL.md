# The QOS HAL

The model is in `../fprisc/docs/HAL.md`: the language has a **runtime** and,
under it, a small **machine layer** per system; the **HAL** -- the devices a
program sees -- is QOS's. This page is what QOS owns.

## One interface, two backings

`qos/appside/qos_abi.h` is the interface: `qos_hal_t`, a versioned table of
function pointers (ABI v13), plus the boot record and the syscall tags.

| | Backing | Where |
|---|---|---|
| **QOS Native** | drivers on the virt board | `hal/virt/`: `plic.fpr` (irq claim/mask/ack, FP-RISC over typed layouts; `plic.c` is the rv32 fallback), `net.c` (virtio net and the TCP stack), `blk.c` (virtio block), `pins.c` (the pin bus), `devices.c` (names `net` and `blk` to the machine layer) |
| **QOS Portable** | the host OS | `hal/unix/`: `gfx.c`, `snd_raw.c`, `net_raw.c`, `blk_raw.c`, `evdev_raw.c`, `tty_raw.c`; `qos/portable/haltab.c` fills the table from them |

`hal/virt/qos-virt.mk` owns the rules and the export list for the native
drivers, for all three places that link them: a bare-metal image built from this
tree (`make bare-metal`, which hands them to the compiler's Makefile as
`EXTRA_RT`), the native kernel (`qos/Makefile`), and `tools/build-process-app.sh`.

## Still mixed

`qos/appside/hal.c` holds both an app image's machine layer and its device
bindings. It is listed in `../fprisc/docs/HAL.md` as still to do. (The kernel's
loaders were `hal/core/`; they are `loader/` now, since they are not a HAL.)
