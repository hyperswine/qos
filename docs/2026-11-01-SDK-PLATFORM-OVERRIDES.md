# `[platform]` overrides for `kind = "app"`: step 3 done

Date: 2026-11-01. This implements step 3 of
[SDK-PROCESS-APPS.md](2026-11-01-SDK-PROCESS-APPS.md), on top of
[steps 1 and 2](2026-11-01-SDK-PROCESS-APPS-STEPS-1-2.md). A `kind = "app"`
project can replace an SDK platform file or add its own C, but only by
naming it in `qos.toml`, and every such file is printed and recorded.
Nothing is released.

## The manifest

```toml
[platform]
c-sources = ["native/sensor_bridge.c"]   # extra C or assembly linked into the image

[platform.override]
"appside/hal.c" = "native/my_hal.c"      # replaces the SDK's file of that name
```

- **`[platform]` is for `kind = "app"` only.** A desktop app links no
  platform files, so the table is refused there.
- **Which names can be overridden.** The `.c` and `.S` files in `sdk.json`'s
  `platformFiles`. That is the app-side entry, HAL and support code, the
  loader, `sha256.c`, `hal/net_actor_bridge.c`, the FP-RISC runtime units
  and `machine/unix/ctx_a64.S`. An unknown name is refused, and the
  message lists the valid ones.
- **What cannot be overridden.**
  - Every header (`qos_abi.h`, `store_abi.h`, `fpr.h`, `i32.h`,
    `vec_layout.h`). These are the ABI; a program that needs a different
    ABI needs a different SDK.
  - The linker script. It is the image layout the host loads.
- **File rules.** The replacement has the same suffix as the file it
  replaces. Override and source paths are relative, inside the project,
  and exist. A file is listed once: no repeated `c-sources`, and no file
  is both an override and a source.

## How they are built

- **Overrides.** The SDK's cached platform objects are used for every file
  that is not overridden. An override is compiled from an overlay of the
  SDK's platform folder: the build copies that folder into its temporary
  directory and puts the project file in the SDK file's place.
  - The override therefore sees exactly the SDK's headers and relative
    includes (`entry.c`'s `../store_abi.h` still works), and nothing from
    the project. Code an override shares with other project files belongs
    in `c-sources`.
  - `hal/net_actor_bridge.c` is included by `appside/hal.c`, not compiled
    by itself. Overriding it recompiles `hal.c` against the replacement.
- **`c-sources`.** They compile where they are, with the same flags and the
  SDK's include paths, and link after the platform objects. A quoted
  `#include` looks beside the source first, so a project file named like an
  SDK header (`qos_abi.h`, `fpr.h`, ...) in a source's folder would replace
  the SDK's. That is refused by name.
- **No caching yet.** Project files are compiled on every build; they are
  small.

## Where they show

- **`qos build`** prints one line per file before building:
  `qos: platform override: appside/hal.c replaced by native/hal.c (sha256 ...)`
  and `qos: platform source added: native/sensor.c (sha256 ...)`.
- **The archive manifest** lists them after its top-level keys:

  ```toml
  [[platformOverrides]]
  kind = "override"
  file = "appside/hal.c"
  source = "native/hal.c"
  sha256 = "d6d0b5b1..."

  [[platformOverrides]]
  kind = "added"
  source = "native/sensor.c"
  sha256 = "54153f23..."
  ```

  The host's manifest reader (`programs/mods/manifest.fpr`) takes known
  top-level keys and skips tables it does not know, so these tables change
  nothing at load time. A game built this way runs normally.
- **`qos run`** prints them from the archive before it starts the host.
- **The disk installer** does not show them. The proposal said it would,
  but `kind = "app"` images are not installed on a Main disk (the installer
  takes only desktop plugins), so `qos run` is where they are shown.

**No shadowing.** The builder never searches the project for platform
files. Stray copies (`platform/appside/hal.c`, `appside/hal.c`,
`hal/net_actor_bridge.c`, `qos_abi.h` at the project root) leave the
archive byte-identical.

## Acceptance

`tools/portable-app-check.py` (see steps 1 and 2) now also runs, on the
first project under the sandbox:

1. stray platform copies that would fail to compile: the archive is
   byte-identical to the build without them;
2. an override of `appside/hal.c` (the SDK's file plus a marker string)
   and a `c-sources` file (another marker): the build prints both lines,
   the archive records both with their hashes, both markers are in the
   image, and the project's own game check passes, with `qos run`'s
   override line in the game log;
3. an override of `appside/qos_abi.h`, which is refused.

Result, from an SDK staged at QOS `a1c06d0` (clean) and FP-RISC `94f699b`:
passed, together with the whole steps 1-2 acceptance. Both games built and
passed their checks, the v1 identity check held, and the tampered SDK was
refused. See the [evidence](evidence/2026-11-01-sdk-platform-overrides.json).

The proposal's acceptance item 2 (an SDK with one changed platform byte
gets a different hash, and a project built against it records the new hash)
is covered in two parts:
- a tampered installed file is refused by name;
- `platformSha256` is computed by the stager from the files it copies, and
  the archive records it as `sdkPlatformSha256`.

A rebuild against a restaged, changed SDK was not run.

## Not done

- Step 4: the `qos` command and packager rewritten in Sol or FP-RISC, and a
  shipped `lld`.
