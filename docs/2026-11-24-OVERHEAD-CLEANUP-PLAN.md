# QOS Overhead Elimination Plan

Date: 2026-11-24. Kind: engineering plan and tracking ledger.

This document tracks the ordered passes to eliminate runtime, allocation, I/O,
polling, driver, and binary-size overhead across QOS. Each pass is landed and
verified independently with before/after measurements.

## Pass 1: Binary Size, QLink/SD-SPI Fast Paths, and QLog Metadata Caching — DONE

1. **Dead-code elimination in `qos/Makefile`**
   - Added `-ffunction-sections -fdata-sections` to `CFLAGS` and `-Wl,--gc-sections`
     to the `native` kernel link (`qos/Makefile`, matching
     `hal/spectre/actors/spectre-build.sol`).
   - Left `qos-app.mk` unchanged: `qosapp.pre.elf` builds a runtime symbol export
     table (`tools/mkexports.sol`) so dynamically loaded plugins can resolve
     runtime symbols by name, so `--gc-sections` cannot be applied blindly there.
   - Measured `riscv64-unknown-elf-size` on `qos-native.elf` (pinned `fprisc` `0230c8f1`):
     - **RV64 (`virt`)**: `text` 1,317,862 → 1,239,186 (**-78,676 B / -6.0%**),
       `data` 112 → 104 (-8 B), `bss` 273,256 → 266,168 (-7,088 B),
       total `dec` 1,591,230 → 1,505,458 (**-85,772 B / -5.4%**).
     - **RV32 (`virt32`)**: `text` 1,212,354 → 1,115,634 (**-96,720 B / -8.0%**),
       `data` 68 → 68, `bss` 240,976 → 236,120 (-4,856 B),
       total `dec` 1,453,398 → 1,351,822 (**-101,576 B / -7.0%**).
   - Verified on QEMU: `tools/native-image-check.sol rv64` (3/3 passed) and
     `tools/native-image-check.sol rv32` (3/3 passed).

2. **QLink streaming CRC-16 and zero-copy encode (`hal/link/qlink.c`)**
   - Replaced the bit-by-bit `qlink_crc16` loop (8 iterations/byte) with a
     16-entry nibble lookup table (`crc16_step`, 32 bytes ROM).
   - Streamed CRC incrementally over `head[4]` then `payload[n]` in
     `qlink_encode`, removing the 259-byte stack copy `tmp[]`.
   - Verified with standalone C harness (`cc -O2 -Wall -Wextra`): 256/256
     single-byte and 1000/1000 random buffer CRC + `qlink_encode`→`qlink_input`
     roundtrips passed.

3. **SD-SPI full-page write fast path (`hal/drivers/sd_spi.c`)**
   - Updated `write_page` to write directly from `src` when `len == BLOCK_PAGE`
     instead of copying all 4,096 bytes byte-by-byte into `scratch[]`; partial
     pages use `__builtin_memcpy` + `__builtin_memset`.

4. **QLog cached metadata, batched compaction writes, and `indexNames` (`programs/mods/qlog.fpr`)**
   - Added single-writer `MetaCache` (`CacheNone | CacheV2 Meta | CacheV3 Seal Int`)
     threaded through the storage actor, eliminating 2–3 superblock page reads
     and 1–2 `pageCount` RPCs per append while preserving `pageProbe` on
     read/stats/generation/snapshot paths and refreshing on compaction.
   - Added `sealWriteNp` / `publishNextSealNp` to avoid redundant `pageCount` calls.
   - Batched `writeBuf` compaction writes up to 8 consecutive pages per `writeRun`
     RPC (`writeBufBatch`, `takeBufPages`).
   - Replaced O(N²) `indexNames` string concatenation with `collectIndexNames` +
     `strJoin "\n"`.
   - Verified on QEMU (`make -C qos native` + `qemu-system-riscv64`):
     `tests/qlogreplayreads.fpr`, `tests/qlogblankrange.fpr`,
     `tests/qlogpackedframing.fpr`, and `tests/qlogreplace.fpr` all `HOLDS`.

## Pass 2: Convert Remaining Leaking Service Loops & Timer Actor Spawns — DONE

1. **Converted hand-written `receive` loops to `Sys.loop` / `AC.tidy`**
   - `programs/mods/qsys.fpr`: threaded `AC.tidy` (`AC.tidySmall`) through
     `fileServe` (preserving the 7-arg `fileServe` entry via `fileServeTidy`)
     and `filesServe` (inside `FilesCtx`).
   - `programs/mods/timer.fpr`: converted `loop` to `Sys.loop` and replaced
     per-request `spawn (sleeper me ms)` on Portable (`nat == 0`) with a single
     reusable `sleeperActor` (parks in blocking `receive` when idle, slices long
     waits to 10 ms so newly arrived shorter deadlines are picked up promptly
     with zero spawns).
   - `programs/mods/sysep.fpr`: converted `kbdSub` to `Sys.loop` and unpinned
     `TM = use "timer"` to match `programs/system.fpr` and `std/timer.fpr`.
   - `std/lifecycle.fpr`: converted `loop` to `Sys.loop` and backed off the
     idle `Sys.shutdownRequested` poll from 1 kHz (`1000` us) to 40 Hz
     (`25000` us, 25x fewer wakeups).

2. **Trimmed per-message O(N) / copy churn in `epservice.fpr` and `graphics.fpr`**
   - `programs/mods/epservice.fpr` (`simpleUntil` / `untilStep`): deferred
     `liveLeases` full-list sweep + `Sys.alive` scan to `Open` and `stale`
     messages; `Read`/`Write` check only the target handle's expiry directly.
   - `programs/mods/graphics.fpr`: switched `loop` from per-message
     `AC.boundary` to adaptive `AC.tidy` (`AC.tidySmall`); in `poll`, skipped
     `liveNotes` and `setNote` rebuilds when focus state is unchanged and
     deferred `liveNotes` sweeps to session/focus transitions (`admit`,
     `ctlWrite`, `dropH`, `nextFocus`) and new pollers.

3. **Verification**
   - Native QEMU (`make -C qos native`, RV64 + RV32 built cleanly):
     - `tests/timer.fpr` (`mode=1 sleep50=ok after=ok order=ok`)
     - `tests/timerroute.fpr` (`write=ok fire=ok`)
     - `tests/gfxshare.fpr` (`HOLDS`)
     - `tests/gfxmemory.fpr` (`100000 frames retain under 2 MiB; backend state survives`)
     - Standalone `epservice.simpleUntil` Open/Read/Write/Close check (`HOLDS`)
     - Standalone `std/lifecycle` start → idle `Sys.loop` → `Stop` check (`HOLDS`)
   - QOS Portable (`qosp`):
     - `tests/timer.fpr` (`mode=0 sleep50=ok after=ok order=ok` — reusable sleeper)
     - `tests/kbdread.fpr` (`seq=wxyz00 first=97 second=98 poll=0 HOLDS`)
     - `tests/filesreclaim.fpr` (`HOLDS`)
     - `tests/filelazy.fpr` (`HOLDS`)

## Pass 3: Eliminate 200 us Disk Sleep-Polling & 1 kHz Idle App Loops — DONE

1. **Adaptive disk completion waits (no flat 200 us park on fast I/O)**
   - Portable (`qos/appside/hal.c` `disk_wait`): replaced the immediate 200 us
     `fpr_actor_sleep_us(200)` poll with a brief 10 us bounded spin (100 ticks
     on the 10 MHz clock) to catch fast page-cache hits with zero parks,
     followed by an adaptive sleep ramp (`10 → 25 → 50 → 100 → 200 us`),
     preserving `QOS_BLK_DEADLINE_TICKS` and `QOS_DISK_TEST_SYNC` without
     breaking `qos_abi.h` (ABI v24).
   - Native VirtIO (`hal/virt/blk.c` `blk_rw`): added the same 10 us bounded
     spin + adaptive `10 → 25 → 50 → 100 → 200 us` sleep ramp when `hal_mtime()`
     is active, keeping `200 us` parks during clockless early boot and
     preserving `QOS_POLL_TRIAL` verbatim.

2. **Idle app polling backoff**
   - Moved 1 kHz `Sys.sleepUs 1000` idle loops in `editapp.fpr`, `clockapp.fpr`,
     `diskapp.fpr`, `browserapp.fpr`, `logsapp.fpr`, and `termapp.fpr` to
     `Sys.sleepUs 16000` (16 ms / 62.5 Hz, 16x fewer wakeups while staying
     inside a 60 Hz display frame).

3. **Verification**
   - Native QEMU: RV64 + RV32 `qos-native.elf` builds clean; `tests/qlogreplace.fpr`
     `HOLDS` on QEMU virtio-blk.
   - QOS Portable (`qosp`): `tests/qlogreplace.fpr` (`HOLDS`), `tests/filelazy.fpr`
     (`HOLDS`), and all 6 modified `*app.fpr` modules compiled and ran cleanly.

## Pass 4: QLink Console Coalescing, Double-SHA Launch Fix, and Hash Primitive — DONE

1. **QLink console coalescing (`hal/link/qlink_port.c`)**
   - Split `qport_poll` into `qport_poll_rx` (RX drain + `qlink_poll` + backlog
     replay) and `qport_poll` (which also flushes pending `con_out`).
   - Updated `qport_con_write` to call `qport_poll_rx` and coalesce small
     writes into `p->con_out`, flushing immediately on newline (`'\n'`) or
     buffer full (`QPORT_CON_OUT`), while prompts without a newline flush on
     the next `qport_poll`, `qport_con_read`, or `qport_drain`.

2. **Skip duplicate SHA-256 on process launch (`loader/process.c`)**
   - Added a lock-protected one-shot verification cache (`g_check_cache`)
     keyed on `(qa_ptr, qa_len, ext[0..5], sha[64], relsha[64], head/tail edge
     bytes)` populated by `Sys.checkImage` and consumed by `Sys.placeImageAt`
     so the launcher no longer hashes the full `IMAGE` + `RELOC` bytes twice.
     Direct `Sys.placeImageAt` callers or any changed buffer still run full
     SHA-256.

3. **Runtime primitive for QLog chunk hashing (`hal/blk_pack.h`, `programs/mods/qlog.fpr`)**
   - Added `blkHashSlice(s, off, len, acc)` in `hal/blk_pack.h` (included by
     Portable, Native VirtIO, and SD-SPI), computing the exact 31-polynomial
     mod `1e9+7` fold in a tight 64-bit C loop, and delegated `qlog.fpr`'s
     `hGo` to it (eliminating per-byte FP-RISC recursion and division across
     `hashStr`, `hashPayload`, and `bufferLeafPages`).

4. **Verification**
   - Standalone QLink C harness (`cc -O2 -Wall -Wextra`): `qport-coalesce: PASS`
     (6+6 single-byte writes coalesced into 1 frame on `'\n'`; prompt flushed
     on `qport_poll`).
   - Native QEMU `tools/native-image-check.sol`: `rv64` (3/3 passed) and `rv32`
     (3/3 passed), exercising `Sys.checkImage` → `Sys.placeImageAt` and refusal
     paths.
   - QLog `blkHashSlice`: `tests/qloghashrv32.fpr` (`HOLDS` on RV32 QEMU),
     `tests/qlogreplayreads.fpr` (`HOLDS` on RV64 QEMU), `tests/qlogreplace.fpr`
     (`HOLDS` on both RV64 QEMU and QOS Portable).

## Pass 5: Local Disk Cache Hygiene (Optional / On Request)

- Prune stale `.qos/validation`, `build/`, `qos/build/units/`, and root `*.qa`
  artifacts (~34 GB total) once no longer needed for regression bisecting.
