# Compact FP-RISC runtime integration

The coordinated FP-RISC codegen-162 runtime uses an 8-byte managed owning-slab
prefix on 64-bit Base and QOS. A Cons occupies 32 bytes instead of 48. Raw C
buffers retain their size word. Native ABI is 9 for QOS and the memory plane
ABI is 5; stale images are refused before placement.

QOS now uses raw allocation/free for compiler requests and storage scratch.
Storage retries receive into raw capacity and construct an exactly sized String
once the actual reply length is known. The native root PAP reserves its arity
slot. Boot slab cursors follow the runtime's alignment helper.

Every app registers its constructor table before actors start. A native process
registers through the shared memory plane, so the kernel can copy and release
its values and retains numeric layout metadata after image death. Standalone
portable apps initialize their own registry. This is part of the ABI contract,
not an optional plugin lookup.

`FPR_COMPACT_CELLS=0` selects the diagnostic legacy layout consistently in
compiler emission, C flags and native ABI stamping. Default builds need no
extra flag. Do not combine objects from different layout builds.

Local qualification before final source synchronization:

- Large storage replies at 200 KB, 256 KiB and 300 KB pass on the native arm64
  portable host and RV64 QEMU with one and two harts.
- Native integrity/refusal/vector-process tests pass with virtio versions 1
  and 2 on one and two harts. Old runtime and shared-plane versions, missing
  contracts and corrupted archives are refused; accepted images are reclaimed.
- The FP-RISC record contains independent allocation extent, alignment,
  managed/raw recycling, module metadata lifetime, actor and region tests.

Reproduce from this checkout with `FPRISC_ROOT` pointing at the coordinated
FP-RISC source and a fresh `XDG_CACHE_HOME`:

```sh
python3 tools/kv-large-check.py
python3 tools/native-integrity-check.py
```

These are local host and emulator results. No physical Pi deployment is part
of this change. The broader FP-RISC Base run is tracked in its zero-overhead
execution record.
