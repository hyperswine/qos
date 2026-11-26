# QOS Simplification Review

Date: 2026-11-27. Kind: architectural review and simplification roadmap.

## 1. Is QOS getting more sophisticated?

Yes. Over July–November 2026, QOS grew to **~107k LOC** across ~830 source and test files (`46,946` in `qos/`, `21,479` in `programs/`, `16,090` in `hal/`, `11,545` in `tests/`, `7,328` in `tools/`, `2,481` in `std/`) at ~200 commits/month:

- **Multi-backend target matrix**: Native RV64/RV32 (`virt`, `virt32`), Spectre (`hal/spectre/`), Portable (`qos/portable/` + `qos/appside/`), and `qlink` serial framing (`hal/link/`).
- **Verified, bounded OS services**: `programs/mods/qlog.fpr` (1,793 LOC) with V2/V3 seals, metadata caching, and batched compaction; `epservice.fpr` / `epclient.fpr` / `epdeadline.fpr` for leased, timed endpoints; and `AC.tidy` / `Sys.loop` actor-turn discipline.
- **MVU desktop & Sol-only tooling**: `appsession.fpr` (`AS.run`), `sdk/qos/desktop.fpr`, 80 modules in `programs/mods/`, and `qbuild` / `tools/*.sol` replacing all repo-owned Python and Bash scripts.

However, much of the codebase's perceived weight comes from **duplicated plumbing and transitional layers** rather than intrinsic feature complexity. The same features can be preserved with significantly less code and fewer cross-file edits.

## 2. Where Implementation Can Be Simplified for the Same Features

| Area | Current Complexity | Simpler Equivalent (Same Features) |
| :--- | :--- | :--- |
| **1. HAL & Portable Shim** | `hal/classes/{block,console}` started, but `audio.h`, `clock.h`, `hostfs.h`, `input.h` are still header-only stubs; `qos/appside/hal.c` (705 LOC) + `qos/portable/haltab.c` still bridge an 86-slot `qos_hal_t` ABI table. | Finish `hal/classes/` dispatch + `board.toml` generation (`docs/2026-11-18-DEVICE-CLASSES.md`) so Native and Portable share one class contract without per-class `qos_hal_t` shims. |
| **2. Build & Link Glue** | Four separate build definitions: `Makefile`, `qos/Makefile`, `qos-app.mk` (16.5 KB), and `hal/spectre/actors/spectre-build.sol`. | Consolidate Native, Portable, Spectre, and `.qa` app builds into `qbuild` + declarative board/app manifests, retiring hand-maintained file lists. |
| **3. MVU & App Boilerplate** | Key constants duplicated in `appwire.fpr` and `sdk/qos/desktop.fpr`; identical `navigate` / scroll-key handlers in `diskapp.fpr` and `logsapp.fpr`. | Centralize `AV.navigate` in `appview.fpr`, alias `desktop.fpr` keys to `AW.*` (then `std/keys` on the next `fprisc` pin), and factor shared list/format helpers. |
| **4. Fragmented `programs/mods/`** | 80 modules in `programs/mods/` split tightly coupled logic across `ep`/`epclient`/`epdeadline`/`epservice` and `appwire`/`appsession`/`appview`/`appkit`. | Coalesce tightly coupled pairs (e.g., `epclient` + `epdeadline`, `appwire` + `appsession`) to reduce `release.toml` / `fpr.lock` pin churn. |
| **5. Image Verification Glue** | `loader/process.c` + `loader/imgcache.h` maintain a lock-protected one-entry cache to avoid double-hashing when callers invoke `Sys.checkImage` before `Sys.placeImageAt`. | Replace the two-step protocol with a single `loadVerifiedImage` entry point (or linear verified-image token) and remove `imgcache.h`. |

## 3. Execution Batches

### Batch 1 — Immediate Deduplication Wins (Landed)
- **Batch 1A (`appview.fpr`, `diskapp.fpr`, `logsapp.fpr`)**: Move the duplicated 7-line `navigate` scroll-key handler (`keyUp`, `keyDown`, `keyPageUp`, `keyPageDown`, `keyHome`, `keyEnd`) into `AV.navigate` in `programs/mods/appview.fpr`.
- **Batch 1B (`sdk/qos/desktop.fpr`)**: Replace the 34 copy-pasted raw integer key constants in `sdk/qos/desktop.fpr` with aliases to `AW.key*` from its existing `appwire` import.
- **Batch 1C (`hal/blk_pack.h`, `hal/virt/blk.c`, `qos/appside/hal.c`)**: Extract the duplicated `10 -> 25 -> 50 -> 100 -> 200 us` adaptive I/O backoff into `blk_next_sleep_us()` in `hal/blk_pack.h`.

### Batch 2 — App & Endpoint Module Consolidation
- Merge `epdeadline.fpr` into `ep.fpr` / `epclient.fpr` and `appwire.fpr` into `appsession.fpr` (or `appkit.fpr`) with `release.toml` / `fpr.lock` updates.
- Switch `appwire.fpr` key constants to `std/keys` once the `fprisc` pin advances.

### Batch 3 — HAL & Loader Simplification
- Complete `hal/classes/` adapters for `input`, `clock`, `audio`, and `net`, and generate `qos_hal_t` class tables from the same declarations.
- Collapse `Sys.checkImage` + `Sys.placeImageAt` into a single verified-load path and retire `loader/imgcache.h`.

### Batch 4 — Build Unification
- Move `qos-app.mk` and `qos/Makefile` target file lists into `qbuild` + `board.toml` manifests.
