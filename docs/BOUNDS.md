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
| `MAX_GRANTS 64` (`hal/core/process.c`) | A 64-entry ledger of growth grants, commented "reclaimed on exit", that nothing ever read: grants are shared-buddy slabs reaped with their acbs. | Removed. |

The same day the manifest's interpretation became ONE FP-RISC module,
`programs/mods/manifest.fpr` (lists, no capacity), used by the kernel and by a
host tool; `tools/qainfo-parity.sh` holds `qa.c` to it byte for byte, including
a manifest of 300 permissions with a 1000-byte url. `qa.c` stays until FP-RISC
can run host-side inside qosp: `../fprisc/docs/C-REDUCTION.md`.

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

## Open: the memory layout is one decision

App images are linked non-PIC at a fixed address. Everything here follows from
that:

| Limit | Where |
|---|---|
| the arena's size, `ARENA_MB ?= 2048` | `qos/Makefile`, `qos-app.mk` |
| the arena's END baked into each app by `--defsym=_proc_arena_end`, which **must** equal the host's `ARENA_MB` -- "found as random corruption past ~220 sessions" | `qos-app.mk` |
| the image, `LENGTH = 16M` | `qos/appside/link-qosapp.ld`, `link-qosapp-a64.ld` |
| eight plugin sub-slots of 4 MiB at base + 128 MiB: `QOS_PLUG_SIZE`, `PLUG_MAX 8`, `PLUGSLOT`, and `MOD_MAXATTACH 8` in the runtime | `qos_abi.h`, `qos/portable/main.c`, `qos-app.mk` |
| the base address itself | `qos_abi.h`, `qos-app.mk` |
| one process in the native slot, "image larger than the process slot" | `hal/core/process.c` |

Two steps, the first small:

1. **Reserve, then commit.** Hosted, map a very large `PROT_NONE` /
   `MAP_NORESERVE` range and let the buddy and the counted growth gateway commit
   into it; pass the arena's end in the boot record (which already exists)
   instead of linking it in. That retires `ARENA_MB`, `FPR_HEAP_MB` and the
   must-agree hazard. On bare metal, take the RAM size from the device tree.
2. **Relocatable images.** Link apps and plugins PIC, or keep relocations and
   apply them in the loader. The base address, the 16 MiB image cap, the plugin
   slot count and size, and the macOS problem all disappear together, leaving
   the address space and physical RAM as the only bounds.

## Open: named panics and refusals that could grow

| Limit | At the edge | Direction |
|---|---|---|
| `MAX_MESHES 32`, `MAX_TEXT 4096`, `MAX_INST 16384` (`hal/unix/gfx.c`) | `fpr_cpanic("gfx: ...")` | the staging buffers are already `malloc`ed: double them |
| `QOS_NET_MAXCONN 1024`, each with a static `RXCAP 8192` buffer (`hal/unix/net_raw.c`) | about 8 MiB held whether used or not, and a hard ceiling | allocate a connection's buffer when it opens |
| `QOSP_MAXHARTS 64` (`qos/portable/main.c`) | the hart count is clamped without a message | size from `sysconf` |
| `MAXKBD 8` (`hal/unix/evdev_raw.c`) | the scan stops at eight keyboards; a ninth is not opened | a growing table |
| `secs[8]` in `qa_parse_owned` | refused: "too many sections" | honest, and the format has five sections today |
| `NVOICE 24` (`hal/unix/snd_raw.c`) | voice stealing | ordinary for a mixer; listed for completeness |

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

- Seven scripts in `qos/tests-host/` and `check-all.sh` build with the Linux
  `make qos-app` target, so they fail on Apple Silicon where `qos.py` picks
  `qos-app-macos`. It is the one failing leg of `./qos.py test` on macOS;
  LiveView itself passes every leg with the target swapped.
