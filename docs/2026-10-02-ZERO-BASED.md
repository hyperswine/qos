# QOS moved to 0-based positions

Date: 2026-10-02. Kind: implementation record, the QOS half of fprisc's
`docs/2026-10-02-ZERO-BASED.md`. That page holds the contract and the
reasoning. FP-RISC's position primitives (`charAt`, `substr`,
`strIndexOf`/`From`, `!`, `Vec.get`/`set`) are now 0-based, and "not found"
is -1. Their names did not change. Every QOS call site moved in the same
change.

## QOS's own helpers

- **`mods/qar` `extent`** returns a 0-based offset; a bad table gives -1.
  The `ipos - 1` / `rpos - 1` its callers used to apply before handing an
  extent to C are gone (`system.fpr`, `tests/nativeimage.fpr`).
- **`mods/coreutil`**: `wordAt s i n` takes a 0-based start and an exclusive
  end; `parseDigitsAt` is 0-based.
- **The `slice s i j` helpers** in `system.fpr` and `mods/manifest` stay
  inclusive, but are now 0-based.
- **Not found is -1:** `findByte`, `findSlash` and `segSlash` now return -1
  when there is no match. One exception: fprlive/liveview `findSub` returns
  the index just past a match, so 0 still means none (commented).
- **svc `segAfter`**: every literal start moved down by one.
- **qlog**: an entry's offset is 0-based (its bulk walkers, `writePages` and
  `readPayload`).
- **Vectors:**
  - scene2d instance `n` occupies slots `n*10 + 0..9`.
  - voxel's world, lightmap and latency-ring slots are 0-based.
  - matrixkpd's `nth1` is now `nth0`.

## Pins

Five modules were re-committed and their pins moved: uart `8753d450`,
coreutil `00b87d74`, svc `7a8f8240`, qlog `7b69b12a`, tui `af7fad6c`
(`fpr.lock`). timefmt and timer use no positions and keep their versions.

## Verified

- QOS smoke and `check-all.sh`, in the same gate run as fprisc's suites.
- The native QAR2 process load.
- The native image, plugin imports and qsys checks.
- QAR info parity with Python (`qainfo-parity.sh`).
- The disk checks.
