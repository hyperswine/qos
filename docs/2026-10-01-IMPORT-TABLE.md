# Portable plugins bind by name: the import table

Date: 2026-10-01. Kind: implementation record. The third step of the order
agreed for removing privileged identities:
[DISPLAY-BUFFERS](2026-10-01-DISPLAY-BUFFERS.md),
[PROCESS-IMAGES](2026-10-01-PROCESS-IMAGES.md), then this page. It closes the
plugin rows of BOUNDS' "images are linked at a fixed address".

## Before

A QOS Portable plugin (a `.qa` an app attaches at run time; std/loader's
launched apps are plugins too) had a place and a partner chosen at build
time.

**Where it went**

- It was linked at `QOS_PLUG_BASE + PLUGSLOT * 4 MiB`, in a 1 GiB plugin
  window the app reserved out of its own heap.
- Two plugins built for the same slot could not be loaded together.

**What it was built against**

- It was linked against `plugsyms`: a `PROVIDE(sym = 0x...)` script made from
  `nm` of one particular shell build, about 1,970 absolute addresses.
- Under any other shell build its calls went to the wrong place. A shell
  stamp (`shell = <sha>`) and a host check ("matched-set REFUSED") turned
  that silent corruption into a refusal, and `qos-app.mk` carried "TWO LAWS,
  both previously paid for in blood" about the rebuild order.

**How the host was involved**

- The host placed the plugin in the window.
- The app's `fpr_in_heap` excluded the window by address.

## Now

A plugin is memory in the app's heap, and it binds to the app's runtime by
name.

**What a plugin needs from an app** was measured with `nm` on the built
plugins: 46 or 47 symbols each.

- About 33 are `fpr_g_*_callN` primitives and 5 are `fpr_prim_fn_*`.
- 5 are runtime C functions (`fpr_alloc`, `fpr_applyN`, `fpr_panic`,
  `fpr_stack_grow`, `fpr_fuel_exhausted`).
- 3 are data: `fpr_true`, `fpr_false`, `fpr_unit`.

Everything else (the prelude, its modules) the plugin already carried as its
own copy. Contrary to two old comments, `PROVIDE` only fills undefined
symbols, so the plugin's own definitions always won.

**Build** (`qos-app.mk` `plugin-qa-a64` / `plugin-qa-x64`)

1. Compile as before (`fprc --plugin`).
2. A first link at 0 with `--unresolved-symbols=ignore-all` shows what the
   plugin imports.
3. `tools/mkimports.py` writes `imports.s`:
   - **A function** gets a stub inside the plugin that jumps through a slot
     (`__qosimp_c_<name>`; `adrp`/`ldr`/`br x16` on AArch64,
     `jmp *slot(%rip)` on x86-64).
   - **Data** gets a placeholder of its ABI size (`__qosimp_d<n>_<name>`),
     which the loader fills with a copy. Only immutable, fixed-layout
     objects may be imported this way: the Unit/True/False headers (8
     bytes), a primitive's static closure `fpr_g_<name>` (a 32-byte
     `pap0_t`), and x86-64's `fpr_g_tlsoff` (set once at boot). Nothing in
     the runtime compares them by address (checked).
   - **Any other import** that is not a runtime `fpr_` symbol is refused by
     name at build time.
4. The real link at 0 with `--emit-relocs`, and a second at 256 MiB.
5. `tools/mkqa.py --relocatable --imports --check-moved` writes two
   sections:
   - **RELOC:** the absolute words to move. It now knows AArch64
     (`R_AARCH64_ABS64`) and x86-64 (`R_X86_64_64`) as well as RISC-V. Page
     offsets (`*_ABS_LO12_NC`) count as position-free, because the image
     always moves by a multiple of 64 KiB. Any other absolute relocation is
     refused.
   - **IMPORT:** one line per slot or placeholder, `c|d <offset> <size>
     <name>`.

   The moved link must differ from the first at exactly the RELOC words.

   `appa.qa`: 168 relocations, 47 imports.

**App** (`qos-app.mk` app rules, `tools/mkexports.py`)

- The app is linked twice. The first link learns its symbols, then
  `mkexports.py` writes `qos_exports`: every global `fpr_` symbol except
  the program's own `fpr_fn_`/`fpr_obj_` and module tables, as
  `{name, address, size}` rows sorted by name.
- The table names its symbols (`.quad sym`), so the second link resolves it
  and nothing has to reach a fixed point.

**Attach** (`Plug.attach` → `Sys.attachImage id abi sha nums [IMAGE, RELOC,
IMPORT]`, `qos/appside/entry.c`)

1. The app takes a block from its own buddy and places the image on a 64 KiB
   boundary.
2. It moves the RELOC words (`fpr_qaimg_relocate`; `loader/qaimg.c` is now
   linked into apps).
3. It completes every import from `qos_exports` by binary search. Missing
   names are collected and refused at once: "the plugin needs X, Y, which
   this app does not export". A data import whose size differs is refused
   too.
4. Syscall tag 4 asks the host to publish the code: the host checks the ABI
   stamp, the IMAGE sha, that the block lies inside the app's arena, the
   page alignment, and that code and writable data are on separate pages.
   It then flips the code to r-x, clears the instruction cache, and returns
   the module table's address.
5. The app registers the block as an image (pid 0, never unloaded; its cells
   are statics to `fpr_in_heap`), then the module table.

ABI v16. `qos_plugin_t` lost its `shell` span, and `base` is now where the
app placed the image.

**Removed:**

- `PLUGSLOT`, `PLUGBASE`, the `plugsyms`/`plugsyms-*` targets and scripts;
- `mkqa --shell-of` and the shell stamp check;
- the host's placement and its overlap list;
- the 1 GiB plugin window (`QOS_PLUG_BASE`/`SIZE`, the app's
  `buddy_reserve_range`, and fprisc `fpr_in_heap`'s window exclusion);
- the stale `qos/tests-host/plugload_check.c`, which no longer built and was
  in no gate;
- every `make plugsyms` / `PLUGSLOT=` in check-all, `qos.py`,
  `tools/qsys-check.sh` and `tools/fprd.py`. fprd's `plugin:<slot>:<id>`
  token still parses; the slot is ignored.

## Verified

- **`tools/plugimports-check.sh`** (new check-all leg) builds `plugmini.qa`
  and `plugneeds.qa` once.
  - It runs `tests/qload.fpr` with them, then rebuilds the shell as
    `tests/plugimports.fpr` and runs it on the same disk. The same
    `plugmini.qa` attaches under the second shell build and computes
    40+2=42.
  - `plugneeds.qa` imports `Sys.notInAnyApp` and is refused with "the plugin
    needs fpr_g_Sys_x2enotInAnyApp_call1, which this app does not export".
- **The apps leg** (`tests/apps.fpr`, appa/appb) holds with the plugins
  published at `0x1ffffb60000` and `0x1ffff520000`. That is about 1 TiB from
  the app image at `0x10000000000`, out of reach of any PC-relative
  instruction, so the slots are what make it work.
- **Every plugin leg in check-all** now builds relocatable plugins with no
  `plugsyms`: sysdisk, qsys, livereload, pathnotes, loaderfail, qsysfail
  and selfhost.

## Not done

- **x86-64 is built but not run here.** The x86-64 rules (`plugin-qa-x64`,
  the x86-64 relocation rules, the `jmp *slot(%rip)` stub) were written but
  not built or run. This Mac and the arm64 Linux VM are both AArch64; they
  need an x86-64 host to verify.
- **The app image is still linked at the arena's base.** Relocating it
  would retire the last fixed address, `QOS_SLOT_BASE`.
- **Plugins are never unloaded**, as before. Their blocks are registered as
  pid 0 images.
- **The export table is the whole runtime** (about every global `fpr_`
  symbol). It is a contract by name: renaming a runtime symbol a plugin
  imports refuses that plugin by name until it is rebuilt. The ABI stamp
  still guards layout changes.
