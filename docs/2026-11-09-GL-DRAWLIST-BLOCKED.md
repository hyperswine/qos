# GL draw list in FP-RISC: slice 1 is blocked on the compiler

Date: 2026-11-09. Kind: blocker report for slice 1 of
[C-TO-FPRISC](2026-11-08-C-TO-FPRISC.md) section 8. No code change is made by
this page.

Baseline: QOS `4e60743`. FP-RISC pin `e138e654332f9e016a8ee9ffedd330f40cd146c9`
(`fprisc.lock.json`, unchanged), compiler built from that revision.
Evidence: [evidence/2026-11-09-gl-drawlist/](evidence/2026-11-09-gl-drawlist/).

Slice 1 was: move the GL scene walk, sort and staging out of
[hal/unix/gfx.c](../hal/unix/gfx.c) (`walk_entity`, `walk_list`,
`gfx_bind_instances_at`'s staging, `draw_translucent`'s sort, `retain_ui`)
into FP-RISC using the raw-library-unit recipe of section 6, so the C side
receives a flat draw list.

**Short answer: the recipe cannot produce code for any machine `gfx.c` runs
on.** Raw library units are RISC-V only, and `gfx.c` is built only for posix
hosts on arm64 and x86-64. The plan's section 4 and section 6 were written
from the virt drivers, where this never comes up. Per the slice brief, I
stopped here rather than working around it in C.

## 1. Where `gfx.c` runs

`gfx.c` is linked into exactly three things, all `fpr build --system=posix`
host executables ([qos/Makefile](../qos/Makefile)):

| Target | Host | ISA |
|---|---|---|
| `qosp-gl` | macOS (GLFW, desktop GL) | arm64 or x86-64 |
| `portable-es` / `qosp-es` | Linux, Pi and Buildroot (EGL, GLES 3.1) | arm64 |
| `qos/tests-host/gfx_input_check.c` | the build machine | arm64 or x86-64 |

There is no RISC-V build of `gfx.c` and no bare-metal one. Virt has no GPU tier.

## 2. Blocker 1: raw library units are RV64/RV32 only

The recipe's step 2 is `fprc --profile=bare-metal-builtin --arc --raw --lib
--export=...`. A one-function F32 unit
([rawf32.fpr](evidence/2026-11-09-gl-drawlist/rawf32.fpr)) compiled at the pin
([raw-unit-targets.txt](evidence/2026-11-09-gl-drawlist/raw-unit-targets.txt)):

| Flags | Result |
|---|---|
| `--profile=bare-metal-builtin` (RV64) | builds, exports `qos_gfx_yaw_cos` |
| `--system=bare-metal --target=a64 --profile=builtin` | `profile builtin supports scalar RV64 or RV32 only` |
| `--system=bare-metal --target=x64 --profile=builtin` | same |
| `--system=posix --target=a64mac [--profile=builtin]` | `profile builtin runs on the bare-metal system only, not posix` |

Both refusals are deliberate checks in `compiler/Compile.hs` (the profile
matrix and the builtin target check). Both are still there on fprisc `main`
(`130c36d`, 50 commits past the pin). `--arc`, `--raw` and `--export` all
require profile builtin, so there is no other flag combination to try.

## 3. Why a hosted (Base) FP-RISC walker is not a substitute

`qosp` is itself an FP-RISC Base program, so "write the walker in `qosp.fpr`
and call it from `gfx.c`" looks possible. It is not, for a reason the raw-unit
recipe exists to avoid:

- `gfx_render_scene` runs on the **app's** graphics-service thread, reached
  through the app-side HAL table (`qos/portable/haltab.c`
  `.gfx_render`/`.gfx_render_ui`). It walks the **app's** heap value.
- On arm64 the app keeps its hart in x28, and the host's C is built
  `-ffixed-x27 -ffixed-x28` so it never touches it (`QOSP_DEFS` in
  [qos/Makefile](../qos/Makefile)). Hosted FP-RISC code expects *its own*
  runtime's hart in that register. Calling host FP-RISC code from the app's
  thread would run it on the app's hart.

A raw unit has no runtime, no hart, no allocation, which is why it is safe on
someone else's thread. That property is what is missing on arm64/x86-64.

This is reasoning from the build flags and the call path, not a crash I
reproduced.

## 4. Blocker 2: byte identity needs the same trig, and it is not the same

Acceptance asks for a draw list byte-identical to the C walker's. The C
walker computes each model matrix in float32 with libm `cosf`/`sinf`
(`m4rotY`). FP-RISC `F32.sin`/`F32.cos` are not libm. They are the runtime's
own double-precision range reduction and polynomial, rounded to float
(`fpr_prim_fn_F32_x2ecos` in fprisc `runtime/runtime.c`).

Measured on this Mac (Apple libm), over every yaw the walker can produce from
an Int milli value in -100,000..100,000
([trig-diff.c](evidence/2026-11-09-gl-drawlist/trig-diff.c),
[trig-diff.txt](evidence/2026-11-09-gl-drawlist/trig-diff.txt)):

| | Inputs | Results that differ |
|---|---:|---:|
| `sinf` vs `F32.sin` | 200,001 | 64 (0.032%) |
| `cosf` vs `F32.cos` | 200,001 | 58 (0.029%) |

UI scenes use yaw 0, where both agree exactly. Scenes that turn entities
(`programs/terra2.fpr`, `tests/gfxheadless.fpr`) will hit a differing input within seconds. glibc on
the Pi is a different libm again, so the C reference is not one fixed answer
either.

Not checked: whether clang fuses the multiply-adds in `m4mul` into FMA
instructions under `gfx.c`'s flags. If it does, the FP-RISC side would also
need fused operations in the same places to match bit for bit.

## 5. What would unblock it

Ranked by how much of the original plan each keeps.

1. **FP-RISC: raw library units on a64 and x64** (fprisc work, then a pin
   bump). Lift the builtin target check for `--raw --lib` exports, with a
   hosted-ABI variant that touches no hart register (on arm64, never x27/x28).
   The typed-IR backend already emits arm64 and x86-64, so this is most
   likely target-check, ABI and test work rather than a new backend. It also
   needs F32 arithmetic inline (not through `$arc.F32*` runtime calls) so the
   unit stays runtime-free. This keeps the plan's recipe exactly. Slice 2
   (`qos/portable/store.c`) and slice 3 (`hal/unix/tty_raw.c`,
   `evdev_raw.c`) need the same thing for the same reason: they are also
   host-side C, built into `qosp` on arm64/x86-64. Slices 4 to 8
   (`hal/virt/pins.c`, `loader/process.c`, the virtio drivers) are built into
   the RV64 native kernel and are not affected.
2. **Decide what "byte-identical" means for the trig.** Either:
   - FP-RISC gains `F32.sin`/`F32.cos` that call the host libm when the
     target has one, so both sides use the same function; or
   - the acceptance becomes "identical except the rotation terms, which are
     within 1 ulp", and the differential test checks exactly that; or
   - the C walker is first switched to the runtime's trig (an observable
     rendering change of at most 1 ulp in 0.03% of rotations), and the
     reference is taken after that.
   This is a choice for whoever owns the plan, not a technical unknown.
3. **Move the walk app-side instead** (into `programs/mods/glsvc.fpr`, whose
   service actor already owns the frame) and add a HAL primitive that takes
   the flat list. This avoids blocker 1 entirely but is a different design
   from the one section 8 approved: a new `core/foreign.fpr` primitive, a HAL
   table version bump, a per-frame draw-list value (the 2D camera is an Int
   precisely because a nested per-frame heap value once exhausted the heap on
   a Pi after 20 minutes, see the comment above the camera code in
   `gfx_render_pass`), and the trig question of item 2 is unchanged.

## 6. What I did not do

- No frame-time baseline and no C reference capture: both are only useful
  once a unit can be linked, and the reference depends on the item-2 decision.
- No change to `gfx.c`, the HAL table or any build file.
- `fprisc.lock.json` unchanged. Nothing pushed.
