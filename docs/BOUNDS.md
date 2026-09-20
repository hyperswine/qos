# Bounds: the host, the loader and the memory layout

The QOS half of the bounds register, audited 2026-09-19. The rule, the severity
order and the runtime half are in `../fprisc/docs/BOUNDS.md`: a limit should
come from the machine, a protocol or the programmer; anything else should grow
until memory is the bound; and reaching a limit must never be silent.

## Fixed on 2026-09-19

| Limit | Was | Now |
|---|---|---|
| `QA_MAX_PERMS 32` (`qos/portable/qa.h`) | Permissions past the 32nd were dropped from the manifest with no message, **required ones included**. | `qa_t.perms` is a heap array that doubles. |
| `qa_perm_t.url[96]`, `.mode[16]` | A longer url was cut to fit. For a capability path that is a different, possibly broader, grant. | Owned strings of whatever length the manifest gave. |
| `static char caps[4096]` + `qa_caps_serialize` (`qos/portable/main.c`, `qa.c`) | The serializer returned early when the buffer filled, so granted permissions never reached the app. Co-designed with the 32 cap (32 x ~114 B), which is why it never showed. | Sized exactly to the grants. |
| `copy_tok` on `name`, `id`, `loadMode`, `abi`, `shell` | Cut to fit. The `id` keys the app's store, so two ids sharing a 63-byte prefix would have shared it. | Still fixed-width, but an overlong value is refused: `qa: manifest: id is too long`. |
| `MAX_GRANTS 64` (`loader/process.c`) | A 64-entry ledger of growth grants, commented "reclaimed on exit", that nothing ever read: grants are shared-buddy slabs reaped with their acbs. | Removed. |

The same day the manifest's interpretation became ONE FP-RISC module,
`programs/mods/manifest.fpr` (lists, no capacity), used by the kernel and by a
host tool; `tools/qainfo-parity.sh` holds `qa.c` to it byte for byte, including
a manifest of 300 permissions with a 1000-byte url. qosp itself is an FP-RISC program now
(`qos/portable/qosp.fpr`), plugin attach interprets its archive in the app
(`programs/mods/plug.fpr`), and `qa.c` is deleted: `../fprisc/docs/C-REDUCTION.md`.

Measured with a 101-permission manifest (one url 326 bytes long) and an app that
reports what `Sys.caps` hands it: the old host delivered 32 grants with the last
and the long one missing and said nothing; the new host delivers all 101 whole.

Two build-side fixes from the same day, recorded here because both were silent:

- **The wrong program in the `.qa`.** Every app links to one
  `$(BUILD)/qosapp-a64.elf`. Apple's make is 3.81 with one-second mtimes, and a
  compile takes under a second, so a fresh `.s` could share a timestamp with the
  previous program's elf, which make then kept. `mvutick.qa` held hello's image;
  `dtree`, `bigfree` and `eq` held qdisk2's. The elf rules are `FORCE`d now, as
  their `.s` already was.
- **The arena address on macOS.** macOS 27 reserves `0x180000000`-`0x7000000000`
  in every process (the dyld shared region, then a no-access block), so a hint
  at `0x400000000` is never honoured and re-exec cannot help. Darwin hosts and
  the apps linked for them use 1 TiB (`qos_abi.h`, `qos-app.mk`); Linux is
  unchanged. This is a symptom of the section below.

## Fixed on 2026-09-20: the arena is a reservation (ABI v14)

| Limit | Was | Now |
|---|---|---|
| the arena's size, `ARENA_MB ?= 2048` (`qos/Makefile`, `qos-app.mk`) | 2 GiB, chosen at build time, on both sides | gone: qosp RESERVES address space at the apps' base -- the largest span it can get, 1 TiB down -- and the OS commits pages as the app touches them. `QOSP_ARENA_MB` caps a run. `tests/bigarena.fpr` runs a live heap past the old 2 GiB |
| the arena's END linked into each app (`--defsym=_proc_arena_end`), which **had to equal** the host's `ARENA_MB` -- "found as random corruption past ~220 sessions" | a silent must-agree between two builds | the app reads the span from the boot record at run time; nothing is linked in |
| the image, `LENGTH = 16M` | link error past 16 MiB | 1 GiB |
| the plugin window: 32 MiB at base + 128 MiB, "8 sub-slots of 4 MiB", `PLUG_MAX 8`, and `MOD_MAXATTACH 8` in the runtime | "plugin registry full" at the ninth | 1 GiB at base + 1 GiB; any number of plugins, each of any size, each where it was linked (`PLUGBASE`; `PLUGSLOT` * 4 MiB is only the default spacing); both tables double |
| freed memory | never returned to the OS | the app's buddy gives the pages of a freed block of 1 MiB or more back through the HAL table (`heap_release`) |

The host makes the reservation before its own heap is reserved (its heap is a
reservation too, and would otherwise be free to land on the apps' address):
`hal_heap_before_reserve` in `qos/portable/host.c`. App stacks grow and arity is
unbounded as everywhere else: `../fprisc/docs/BOUNDS.md`.

## Open: images are linked at a fixed address

What is left of the memory layout is one fact: app and plugin images are
non-PIC, linked for an address.

| Limit | Where |
|---|---|
| the base address itself (16 GiB; 1 TiB on macOS, which reserves the range below) | `qos_abi.h`, `qos-app.mk` |
| the 1 GiB image window and the 1 GiB plugin window: a plugin reaches the image's symbols with `adrp`, +-4 GiB on aarch64, so the two must sit within reach of each other | `qos_abi.h`, `link-qosapp*.ld` |
| a plugin's address is chosen when it is BUILT (`PLUGBASE`), so two plugins built for the same address cannot be loaded together, and a plugin must be rebuilt against every shell build (the `plugsyms` absolute-address script) | `qos-app.mk` |
| one process in the native slot (32 MiB after the kernel's heap), "image larger than the process slot" | `loader/process.c`, `machine/virt/link.ld` |

The fix for all four is the same: **relocatable images.** Link apps and plugins
position-independent (or keep their relocations) and have `fpr_qaimg_place` apply
them; a plugin then reaches the shell through a symbol table instead of baked
addresses. That needs the code generators to address external symbols through a
GOT (`A64.hs`, `X64.hs`, and `la` on rv64), which is why it was not done with the
rest: it is a compiler change across three backends, not a loader change.

## Deferred: written down, to be addressed another time

In rough order of worth. The first four are still SILENT and come first.

1. `Host.run`'s `static char result[64 * 1024]`: an app's result string is cut at
   64 KiB by the entry ABI's buffer. Let the app hand back a pointer and a length.
2. `QOSP_MAXHARTS 64`: the hart count is clamped without a message.
3. `MAXKBD 8` (`hal/unix/evdev_raw.c`): a ninth keyboard is not opened.
4. `PIN_TRACE_CAP 4096` (`hal/virt/pins.c`): the pin trace stops recording.
5. Relocatable images (above): the base address, the two 1 GiB windows,
   build-time plugin addresses, the native process slot.
6. `QOS_NET_MAXCONN 1024` with a static 8 KiB buffer each; the virt TCP table
   (`NETCONN 4`); `MAX_MESHES 32`, `MAX_TEXT`, `MAX_INST` in `gfx.c`; `NPINS 32`.
   All named panics or refusals: the table below.
7. The terminal tier has no text-input event and no terminal mouse
   (`docs/INPUT.md`).

## Open: named panics and refusals that could grow

| Limit | At the edge | Direction |
|---|---|---|
| `MAX_MESHES 32`, `MAX_TEXT 4096`, `MAX_INST 16384` (`hal/unix/gfx.c`) | `fpr_cpanic("gfx: ...")` | the staging buffers are already `malloc`ed: double them |
| `QOS_NET_MAXCONN 1024`, each with a static `RXCAP 8192` buffer (`hal/unix/net_raw.c`) | about 8 MiB held whether used or not, and a hard ceiling | allocate a connection's buffer when it opens |
| `QOSP_MAXHARTS 64` (`qos/portable/main.c`) | the hart count is clamped without a message | size from `sysconf` |
| `MAXKBD 8` (`hal/unix/evdev_raw.c`) | the scan stops at eight keyboards; a ninth is not opened | a growing table |
| `static char result[64 * 1024]` in `Host.run` (`qos/portable/host.c`) | the app's result string is cut at 64 KiB by the entry ABI's buffer | let the app hand back a pointer and a length |
| `NVOICE 24` (`hal/unix/snd_raw.c`) | voice stealing | ordinary for a mixer; listed for completeness |
| `NPINS 32`, `PIN_TRACE_CAP 4096` (`hal/virt/pins.c`) | a pin past 31 panics by name; the pin trace **stops recording** at 4096 entries without saying so | size from the board description; make the trace a ring or report the truncation |
| `NETCONN 4`, `RXRING 16384`, virtqueue `QSZ 8` (`hal/virt/net.c`, `blk.c`) | small fixed TCP table | allocate connections from the heap |

## Legitimate, left alone

- The QLOG disk is the size of its device, and a full data partition is
  `Err "data partition full"`.
- `QOS_BLK_PAGE 4096`, the audio `RATE` and `CHUNK`, evdev key codes.
- Telemetry rings: `PEND_N`, `PEND_W` in `hostlog.c`.
- `INJ_CAP 128`: the injected-key ring drops its oldest entry when full, by design.

## Not audited

`qos.py`, the tools under `tools/`, and the FP-RISC programs and services in
`programs/`, `programs/mods/` and `std/`.

## Found along the way (not bounds)

- FIXED: seven scripts in `qos/tests-host/` and `check-all.sh` said
  `make qos-app` while `qos.py` chose `qos-app-macos` on Apple Silicon, so they
  failed there -- the one red leg of `./qos.py test`. `qos-app.mk` owns the
  choice now (`qos-app`, `plugsyms`, `plugin-qa` dispatch on the host), and
  `qos.py` no longer makes it. `./qos.py test`: 11/11 on macOS.
- `check-all.sh` on macOS, first run (2026-09-19): 103 legs, 96 pass.
  Fixed on the way: the QAR2 integrity leg guarded only its python step with
  `||`, so a miss in the check fell to `set -e` and ended the WHOLE sweep with
  no `LEG FAILED` line (it fired when the FP-RISC host reworded the refusal;
  the wording `IMAGE sha256 mismatch` is restored -- a refusal's text is
  interface); `tools/build-process-app.sh` still said `QOS=../qos` from its
  `fp-risc/tools/` days, so both native process-launch legs failed before
  reaching a kernel; BSD `wc -l` pads its count, which four string comparisons
  did not expect. The seven that remain, none from this work:
  - four are the case-coverage pass refusing `base.removeAt`'s
    guard-then-single-arm `case` (`nn`, `plotdemo`, `algebra`, `sol-scripts-check`);
  - `both.sol` is compiled ahead-of-time for bare metal, which the profile
    matrix now refuses ("profile sol runs on the posix system"): the leg and
    the rule disagree;
  - `mlpipe` wants GPU uniform captures, and the Darwin build links no GL;
  - `RVV=1` times out under this QEMU, with the HAL as it was before today too.
