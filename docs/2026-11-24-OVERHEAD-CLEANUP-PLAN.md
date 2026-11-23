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

## Pass 2: Convert Remaining Leaking Service Loops & Timer Actor Spawns

1. **Convert hand-written `receive` loops to `Sys.loop` / `AC.tidy`**
   - `programs/mods/qsys.fpr`: `fileServe` (L194) and `filesServe` (L368).
   - `programs/mods/timer.fpr`: `loop` (L59), plus replace per-request
     `spawn (sleeper me ms)` on Portable (`nat == 0`) with a single reusable
     sleeper or bounded wakeup.
   - `programs/mods/sysep.fpr`: `kbdSub` (L234).
   - `std/lifecycle.fpr`: `loop` (L60), eliminating both the hand-written
     recursion and the 1 kHz `Sys.sleepUs 1000` polling loop for shutdown.

2. **Trim per-message O(N) / copy churn in `epservice.fpr` and `graphics.fpr`**
   - `programs/mods/epservice.fpr` (`simpleUntil` / `untilStep`): sweep expired
     and dead leases on `Open` (or periodically / near cap) instead of calling
     `Sys.alive` and rebuilding the handle list on every `Read`/`Write`.
   - `programs/mods/graphics.fpr`: switch `loop` from per-message `AC.boundary`
     to adaptive `AC.tidy`, and sweep `notes` only on focus/session transitions
     rather than every `Poll`.

## Pass 3: Eliminate 200 us Disk Sleep-Polling & 1 kHz Idle App Loops

1. **Completion-driven disk waits**
   - Portable (`qos/appside/hal.c` `disk_wait`, L283): replace the 200 us
     `fpr_actor_sleep_us(200)` poll loop with a wake signal from the disk worker.
   - Native VirtIO (`hal/virt/blk.c` `blk_rw`, L418): wire virtio-blk PLIC IRQ
     completion wakeup instead of 200 us sleep-polling.

2. **Idle app polling backoff / blocking waits**
   - Move 1 kHz `Sys.sleepUs 1000` idle loops in `editapp.fpr`, `clockapp.fpr`,
     `diskapp.fpr`, `browserapp.fpr`, `logsapp.fpr`, and `termapp.fpr` to
     blocking waits or coarser intervals matching M6's 20 ms launcher cadence.

## Pass 4: QLink Console Coalescing, Double-SHA Launch Fix, and Hash Primitive

1. **QLink console coalescing (`hal/link/qlink_port.c`)**
   - Stop calling `qport_con_flush` at the end of every small `qport_con_write`;
     flush on newline, buffer full, `qport_poll`, or `qport_drain`.

2. **Skip duplicate SHA-256 on process launch (`loader/process.c`)**
   - Cache the last verified `(qa_ptr, qa_len, ext, sha, relsha)` or return a
     verified token from `Sys.checkImage` so `Sys.placeImageAt` does not hash
     the full `IMAGE` + `RELOC` bytes twice.

3. **Runtime primitive for QLog chunk hashing**
   - Replace per-byte FP-RISC division in `qlog.fpr` `hashStr` (`hGo`) with a
     small C runtime primitive computing the exact same 31-polynomial mod 1e9+7
     hash.

## Pass 5: Local Disk Cache Hygiene (Optional / On Request)

- Prune stale `.qos/validation`, `build/`, `qos/build/units/`, and root `*.qa`
  artifacts (~34 GB total) once no longer needed for regression bisecting.
