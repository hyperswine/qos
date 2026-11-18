# The BLOCK class and board manifests

Date: 2026-11-18. Kind: implementation record, milestone M2 of the Spectre-84
plan (the [device classes proposal](2026-11-18-DEVICE-CLASSES.md), steps 1, 2
and 4 for block storage). Sources: QOS after `9a61c37`, FP-RISC `69da12ca`
(machine layer).

## What changed

**Device classes in the device table (FP-RISC `machine/virt/devtable.h`).**
An entry now carries a class (`FPR_DEV_BLOCK`, `FPR_DEV_SERIAL`, ...), an IRQ,
an ops table, the driver state the ops take and an optional `irq_top` hook.
Older entries leave them zero. `devtable_entry_of` turns a `Device` back into
its entry; `hal_dev_by_class` finds the n-th instance of a class.

**The BLOCK class (`hal/classes/block.h`, `block.c`).** The header is the
contract: 4 KiB pages; `pages`, `read` (one or more pages), `write_record`
(a header page then payload pages, zero-padded), `flush`; `range_max`; what a
driver may assume and how it fails. `block.c` holds the FP-RISC primitives
(`blkPages`, `blkRead`, `blkReadRange`, `blkWrite`, `blkWriteRecord`,
`blkFlush`, `blkWaitInbox`) once for every driver: each finds the instance
behind its `Device`, checks types, pages and sizes, and calls the ops.

**Drivers.**

| Driver | File | Was |
|---|---|---|
| virtio-blk | `hal/virt/blk.c` (`virtio_blk_ops`) | the same file, defining the primitives itself |
| SD over SPI | `hal/drivers/sd_spi.c` | two copies inside `hal/spectre/actors/boot/hal.c` and `vfs/hal.c` |
| RAM (reference) | `hal/drivers/memblk.c` | new |

Each has a descriptor, `hal/drivers/DRIVER.json`: class, ops symbol, state
type, setup, parameters, sources.

**Board manifests (`bsp/BOARD/board.json`, `tools/board.sol`).** A board lists
its device instances: name, driver, base, IRQ, parameters, and an optional
`when` macro. `tools/board.sol` generates the board's `devtable.c` (defining
`hal_devtable_ext`), `sources.txt` and `board.mk`. `hal/virt/qos-virt.mk`
includes the generated `board.mk` (`QOS_BOARD`, default `virt`), the process
image builder links the same list, and the Spectre boot image's table comes
from `bsp/spectre54` or `bsp/spectre84`. `hal/virt/devices.c` is gone: the
board file is the one place a board's devices are named. Plugging a driver
of an existing class into a board is now a driver file, its descriptor and
one manifest line; the RAM driver went in that way.

## Findings on the way

- **`programs/mods/qlog.fpr` flushed with `blkFlush 0`.** Every old driver
  ignored the device argument; the class checks it, and the Spectre image
  stopped at `blk: not a Device` until the call passed the device.
- **Range errors on Spectre** used to panic the machine (`fpr_cpanic`); under
  the class they fail-stop the calling actor, as on virt.
- **The native kernel and process images did not link on main**: the runtime's
  `buddy.c` and `runtime.c` use count-leading/trailing-zeros builtins that need
  libgcc. Both links now add `-lgcc`.
- **The Sol-only cutover left no runner for native test kernels.**
  `tools/native-fixtures.sol` runs `tests/NAME.fpr` as the kernel on QEMU
  virt with a fresh disk and checks its `#: expect` line (`#: cflags` passes
  test switches). Expectations the retired scripts held were added to
  `disknative`, `blocklifecycle`, `blockmemory` and `blockservice`.
- **`blockservice` fails on main before and after**: `std/blockio.fpr` lacks
  `unsafe` signatures the current compiler requires (the known std safety rot).

## Checks

- Native fixtures on QEMU virt: `blockrange`, `disknative`, `blocklifecycle`,
  `blockmemory` and `blockconform` pass. `tests/blockconform.fpr` runs the
  same contract checks (page reads, padding, a 5,000-byte record across three
  pages, stale-data clearing, flush) on the virtio disk and on the RAM driver.
- System.qa boots to its app launcher on QEMU virt, and a separately built
  process image installed on the disk runs (`process exited: qar2 process ran`).
- Spectre-84 (built at FP-RISC `69da12ca` with the generated table) boots from
  SD and passes `check-writable.sol warm`, `check-two.sol` and
  `check-two.sol --mailbox` on the board. Spectre-54 builds.

## Not done in this step

Two virtio disks in one image (the virtio driver keeps one static queue; a
second instance needs per-instance state), per-instance grants, and the
serial and console classes, which come with the UART link (M3), where their
first non-UART backend appears. Portable still implements the block
primitives through `qos_hal_t` (`qos/appside/hal.c`); generating its members
per class is the plan's last step.
