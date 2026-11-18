# Device classes: plugging a driver into any backend

Date: 2026-11-18. Kind: design proposal, for review before code changes. Nothing
here is built yet.

## Goal

Writing a driver will always take as long as the device demands. Plugging one in
should not. For a device of a class QOS already knows (block, console, network,
input, display, sound, pins), adding a backend should take two things: the
driver, which implements that class's operations, and one line in the board's
description. No compiler table, ABI table, shim or makefile should need editing,
and the same driver source should serve QOS Native on any board and, where the
hardware is the host's, QOS Portable.

This is the device half of the [multi-board proposal](2026-10-11-BUILTIN-KERNEL.md),
taken in steps that work with today's code. That proposal's services and
`bsp/<board>/board.toml` are where this ends up. The device classes below are the
contracts those services would implement.

## How a driver is plugged in today

Three layers sit under a program
([HAL reference](2026-09-19-HAL.md), [FP-RISC's model](../../fprisc/docs/2026-09-19-HAL.md)):

1. **The machine layer, in FP-RISC** (`machine/<system>/`): boot, context switch,
   a console byte, the timer and register access. Its `device "name"` lookup
   knows the devices the runtime stands on (uart, clint) and, through a weak
   `hal_devtable_ext` hook, whatever a HAL above it adds
   ([devtable.h](../../fprisc/machine/virt/devtable.h)). An entry is
   `{name, dev, setup, ioctl}`.
2. **The devices a program sees, in QOS.** Each is a set of primitives declared in
   [core/foreign.fpr](../core/foreign.fpr) (46 signatures: `blkRead`,
   `blkWriteRecord`, `netPoll`, `glRender`, `sndPlay`, `Pin.*` and the system
   calls). Each resolves at link time to an `fpr_g_` symbol.
3. **The backend**, which supplies those symbols. It is plumbed differently in
   each of the three backends:

| Backend | How block storage is supplied |
|---|---|
| Native, virt | [hal/virt/blk.c](../hal/virt/blk.c) implements the primitives over virtio. [devices.c](../hal/virt/devices.c) names `blk` with a fixed `VIRTIO0_BASE`. [qos-virt.mk](../hal/virt/qos-virt.mk) lists the files for the three links that use them |
| Portable | [hal/unix/blk_raw.c](../hal/unix/blk_raw.c) does the I/O. [haltab.c](../qos/portable/haltab.c) puts it in `qos_hal_t` (`blk_submit`, `blk_done`), and [appside/hal.c](../qos/appside/hal.c) turns those back into the primitives inside each app image |
| Native, Spectre | [boot/hal.c](../hal/spectre/actors/boot/hal.c) and [vfs/hal.c](../hal/spectre/actors/vfs/hal.c) each define `fpr_g_blkRead` and `fpr_g_blkReadRange` again, over the SD card. The build is [spectre-build.sol](../hal/spectre/actors/spectre-build.sol) |

So the one block contract has four implementations, and none of them shares the
code that turns a primitive call into device work.

**What it costs today.**

- *A new driver for an existing class on a new Native board* (an SD card on a new
  board): a machine layer, a C file defining the class's `fpr_g_` symbols with the
  contract's exact behaviour, a devtable entry and a make or Sol fragment. This
  is the closest of the cases to the goal.
- *A second device of a class in one image* (two block devices): not possible.
  Binding is by symbol name, so one image has one implementation of each class.
  The devtable deliberately has "no registry and no capacity".
- *A new device class*: a signature in `foreign.fpr`, a `qos_hal_t` slot (an ABI
  bump, currently v24, after which every app image must be rebuilt), its
  `haltab.c` entry, the `appside/hal.c` shim, the Native driver and its build
  fragment. That is five places in two trees, before any second board.

## What makes it hard

1. **The contract is whatever the first driver did.** No class is written down
   apart from its implementation. Block's operation codes live in `blk.c` and
   `blk_pack.h`. Network is virtio and its TCP stack in one 684-line file. Several
   signatures are still `a -> b`. A new driver learns the contract by reading
   another driver.
2. **Link-time names instead of instances.** A class has exactly one provider per
   image. Nothing names *which* block device, and permissions can only grant a
   whole class (`/services/storage`), not an instance.
3. **Portable and Native have separate plumbing.** Native links primitives
   directly. Portable goes through `qos_hal_t`, an append-only table of 86
   members whose version covers every class at once, so a change to one class
   rebuilds every app.
4. **Each backend has its own build glue.** `qos-virt.mk`, the `native` rule in
   `qos/Makefile` and Spectre's Sol build each decide by hand which files make up
   a board. Nothing describes a board as data.
5. **Spectre sits outside the HAL.** Its UART, SD card and file system are
   bring-up code under `hal/spectre/actors`, with copies per image, so the virt
   drivers' policy work (`blockpolicy.fpr`, `netpolicy.fpr`) does not reach it.

## Proposal

### 1. One declaration per device class

Each class gets a written contract in one file: its operations, their argument
and result types, the error results, and the behaviour a driver must keep (page
size, ordering, what a short read means). From that declaration, a generator
produces:

- the C operations table a driver fills in (`qos_blk_ops`: `pages`, `read`,
  `read_range`, `write_record`, `flush`, ...);
- the FP-RISC signatures that replace the class's lines in `foreign.fpr`, with
  honest types instead of `a -> b`;
- a conformance check that any driver must pass: a differential test against an
  in-memory reference driver, in the style the raw library units `plic.fpr` and
  `virtio.fpr` already use.

The first classes are the ones with more than one backend today: **block**
(virt, unix, Spectre), **console** (uart16550, SimpleRisc UART, tty) and
**network** (virtio, unix sockets). Display, input, sound and pins follow.
Policy stays above the class, as `blockpolicy.fpr` and `mods/qlog` already are.

### 2. Instances in the device table, not symbol names

A driver registers instances: a device table entry gains the class and an
operations pointer, `{name, class, dev, ops, setup}`. For example, `blk0` is a
virtio disk at a given base. The class's primitives take the instance, and each
dispatches through `ops`: one generic `fpr_g_blkRead` per class, written once,
instead of one per backend. `device "blk1"` finds a second disk. Grants can then
name instances (`/services/storage/blk1`). The weak `hal_devtable_ext` hook
stays. Only the entry shape grows, and the machine layer's own uart and clint
entries become console and timer instances like any other.

The indirect call costs nothing measurable next to the device I/O it starts. A
board that wants none can still be generated with direct calls.

### 3. Portable from the same declarations

`qos_hal_t`'s device members are generated per class from the same declarations,
each class with its own version. A host fills a class's operations from
`hal/unix` exactly as a Native board fills them from its drivers. App images then
see the same generic primitives on both runtimes. Changing one class rebuilds
only the apps that use it, and a host that lacks a class leaves it NULL, as
graphics already does.

### 4. A board described as data

A `board.toml` per board lists the machine layer (ISA, harts, memory regions,
link script) and every device instance: class, driver, base address, IRQ and
any parameters. A Sol builder generates the device table and the link inputs
from it, replacing `qos-virt.mk`, the `native` rule's file list and Spectre's
hand-picked sources. This is the file the multi-board proposal describes. Here it
first names drivers and instances, and later names service instances.

### 5. Spectre onto the contracts

Spectre's SD card becomes a block driver, its UART a console driver, and its
file-system prompt runs over the same block policy as virt. The duplicated
`fpr_g_blkRead` definitions go away. The Tang Nano Native port
([proposal](2026-11-12-TANG-NANO-QOS-NATIVE.md)) then starts from a
`board.toml`, not another hand-written build.

## Steps

Each step keeps behaviour unchanged and is checked on the backends it touches.

1. **Block contract.** Write the declaration and the generator. Put adapters in
   front of the four existing implementations, so their code moves rather than
   being rewritten. Add the reference driver and its conformance test.
   *Check:* the native virt QLog boot and file checks, Portable's block and disk
   checks, and the Spectre writable prompt on the board (`check-writable.sol warm`
   and `cold`) all give unchanged results.
2. **Instances.** Extend the device table entry and make the block primitives
   instance-addressed. *Check:* a virt image with two virtio disks reads and
   writes both; grants refuse the instance an app was not given.
3. **Console class**, with the machine layer's uart as an ordinary instance. Then
   input.
4. **`board.toml` for virt and Spectre**, generating what `qos-virt.mk` and the
   Spectre build list by hand. *Check:* byte-identical images, or a recorded
   reason for every difference.
5. **Portable generation**, moving `qos_hal_t`'s device members to per-class
   versions (one ABI version bump for the change itself). *Check:* the Main
   profile and its apps on the desktop and the Pi 4B.
6. **Network, display, sound and pins.** These are the larger contracts. Network
   first splits virtio transport from the TCP stack, so a second network driver
   need not carry the stack.

**Measure of success.** After step 4, adding a driver for an existing class is a
driver file and one `board.toml` line. Record the number of files touched for the
first new driver written that way (the Spectre SD card, or a Tang Nano Native
console) next to the five-place count above.

## Open questions

- **Discovery.** A static `board.toml` fits the FPGA boards. virt can probe
  virtio slots, and a device tree could seed the table on larger boards. Choose
  whether probing fills instances at boot or only checks what the manifest says.
- **The `ioctl` escape hatch.** Keep it per instance for device-specific
  controls, or require every operation to be in a contract. The second keeps
  conformance tests complete.
- **Where drivers run.** Here a driver is linked code behind an operations
  table. The multi-board proposal makes each instance a service actor that owns
  its device. The contracts are meant to fit both. Whether the step from one to
  the other should be per class or all at once is left to that proposal.
- **Interrupts.** Today the PLIC routes a source to the actor that bound it.
  Instances make it natural for `board.toml` to name each instance's IRQ, but the
  binding API itself is unchanged here.
