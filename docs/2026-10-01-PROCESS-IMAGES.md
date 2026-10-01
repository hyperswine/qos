# Native process images are memory like any other

Date: 2026-10-01. Kind: implementation record. The second step of the order
agreed for removing privileged identities: display
([DISPLAY-BUFFERS](2026-10-01-DISPLAY-BUFFERS.md)), then process images (this
page), then the Portable import table. It closes the native row of BOUNDS'
"images are linked at a fixed address", and supersedes the slot guard in
[FAILURE-HONESTY](2026-09-30-FAILURE-HONESTY.md).

## Before

A native process image was linked at the kernel's `_proc_arena_start`, a
fixed 32 MiB region after the heap that the buddy did not own. Because of
that, the slot was a special identity:

- **One process at a time.** A second placement was refused while any
  actor of the first could run.
- **Never freed.** The slot was only reused once the old pid was quiet.
- **Tied to one kernel build.** An image was built against the kernel's
  slot address, read out of the kernel ELF.
- **One global statics window.** The kernel kept a single window for the
  slot's cells.
- **Dangling statics.** A string literal sent out of a process travelled by
  identity, and after a reload it silently pointed at the next image's
  bytes. The failure-honesty record left this out of scope.

## Now

A process image is a block from Memory.qa's buddy, like an actor's slab or
stack. System.qa's loader owns it under a type of record
(`loader/process.c`, `proc_image_t`). Nothing else on the machine treats
it differently.

**Relocatable build** (`tools/build-process-app.sh`, `tools/mkqa.py`)

- The image is linked at 0 with `--emit-relocs` and `--no-relax`. Code
  reaches everything PC-relative (`-mcmodel=medany`), so only absolute data
  words depend on where the image lands: static closures, the module table,
  C function tables and jump tables.
- `mkqa --relocatable` reads the ELF's relocation sections and writes a
  RELOC section: the offsets of the `R_RISCV_64` words, as u32 values.
  Position-free relocation types are skipped: PC-relative code, symbol
  differences, and absolute constants (`SHN_ABS`). Any other type is a build
  error that names it. The image cannot be moved, and placing it would be
  wrong.
- The build links the image a second time, 256 MiB higher.
  `mkqa --check-moved` requires the two images to differ at exactly the
  listed words, each by exactly the link delta. This check is why
  `--no-relax` is there: with relaxation on, the first build differed
  throughout its code. The linker turns PC-relative accesses into
  absolute-address forms when the absolute address happens to be small,
  which is common at base 0. Such an image only works where it was linked.
- The ck-proc image has 453 relocations. Nothing is linked against a kernel
  any more, so any kernel build loads any image.

**Placement** (`Sys.placeImageAt qa [ioff, ilen, roff, rlen] nums caps`)

1. `buddy_alloc` a block: a record, then the image at the next 4 KiB.
2. Copy the image and zero its bss (`fpr_qaimg_place`).
3. Add the block's address to each RELOC word (`fpr_qaimg_relocate`), then
   `fence.i`.
4. Register the block as process pid's image (`fpr_image_add`).
5. Call the image's entry, which spawns its root actor under the pid.

An image that is not relocatable is refused by name: "linked for a fixed
slot: rebuild it".

**Lifetime:** the image belongs to its pid. When the last actor of that pid
has been reclaimed, the image is unregistered and its block goes home:

- `actors.c`'s reaper calls `fpr_pid_quiet(pid)`;
- the loader frees only if `fpr_pid_live(pid)` is 0, so no hart can be
  running that code;
- a flag under `g_img_lock` makes the free happen once.

Processes run at once, as many as memory holds.

**Per-process identity.** The kv capability is scoped by the calling
actor's pid, through its image record's app id. A single global app id was
fine with one slot and would be a capability leak with two processes.

**Statics are values** (fprisc `runtime.c`, `actors.c`; fprisc
`docs/2026-10-01-PROCESS-IMAGES.md`):

- An image's cells have no allocation preheader, so the kernel must not call
  them heap. One bit per buddy minimum block marks image blocks, which makes
  `fpr_in_heap`'s test O(1) and lock-free. The bitmap is sized from the span
  and replaces the old single window.
- The deep copier is told the receiver's pid (`fpr_msg_copy_to`).
  - **Data statics are copied.** A static from another process's image
    crossing to an actor in a different pid gets copied: a string, a header,
    a Result, a device handle.
  - **Functions are refused.** A function into that image's code (a static
    closure, or a heap closure whose code pointer is in the image) cannot be
    copied, so the send is refused and the sender fails alone, fail-stop.
  - **`sendArc` and `sendLinear` across processes** copy instead of sharing
    or moving, for the same reason.

  Within one process, everything still travels as before.

**Removed:**

- the fixed slot (`_proc_arena_start/_end` are gone from `link.ld`, `hal.c`
  and `fpr.h`; the heap is unchanged at 128 MiB);
- the slot claim and occupancy refusal;
- the global statics window on the kernel side (an image's own runtime still
  uses one for its own cells);
- the one-launch-at-a-time `shared_boot_t`;
- `g_shared_live`;
- the build's dependency on a kernel ELF.

## Verified

- **`tools/nativeimage-check.sh`** (check-all, replacing the native-slot leg;
  `tests/nativeimage.fpr` as a test kernel) prints
  `nativeimage: concurrent=both-intact linger=held-then-freed images=0
  memory=returned HOLDS`:
  - two images placed back to back both run and both compute the right sum;
  - a process whose main returned while its child runs keeps exactly one
    image registered until the child ends, then none;
  - afterwards the buddy's free bytes are back within 512 KiB.

  With the `buddy_free` removed, the same test prints
  `memory=NOT RETURNED (124190720 -> 120848384) FAILED`: 3.3 MB, three
  image blocks.
- **fprisc `tests/base/images.fpr`** with `images_probe.c` (`check_base`, 1
  and 2 harts). A fake image registered as process 7 holds a string and a
  closure:
  - the string, sent from process 0, survives the image being poisoned and
    freed;
  - sending the closure ends the sender with "send: a function of another
    process cannot leave it".
- **QAR2 process load and transparent ACBs** (check-all) now build
  relocatable images.

## Not done

- **Remote `fence.i`.** `fence.i` runs on the placing hart only. A block
  reused for new code may be stale in another hart's instruction cache, and
  an image's actors run on any hart. QEMU's TCG keeps instruction fetch
  coherent, so nothing here shows it. Real hardware needs a remote fence by
  IPI before the root is spawned.
- **Closures between processes.** Passing a function to another process is
  refused, not supported. A closure that kept its image alive would need the
  image counted by reference from the receiving side, which the pool model
  has no per-value hook for.
- **Images without a free.** An image whose process never started is freed
  at once (the loader checks after entry). An image whose actor is parked
  forever keeps its block, as any process's memory is kept while it lives.
- **Portable is unchanged.** Apps are still at `QOS_SLOT_BASE` and plugins
  still at build-time addresses with `plugsyms`. That is step 3, the import
  table.
- **The relocation list is RISC-V only** (`R_RISCV_64`). Native images are
  rv64.
