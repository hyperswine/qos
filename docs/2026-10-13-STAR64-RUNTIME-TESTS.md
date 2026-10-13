# STAR64 Linux and FP-RISC execution tests

Kind: executed physical-board tests. Date: 2026-10-13.
This follows [hardware boot confirmation](2026-10-13-STAR64-HARDWARE-BOOT.md).

The board ran native RV64 Linux C and C++ programs, software EGL, and
**27 successful FP-RISC test invocations using an isolated experimental Linux
adapter**. None of these executions used QEMU. The existing ARM64 VM supplied
the cross compiler; SSH transferred the executables to the physical STAR64.

The stock FP-RISC build still does not support `--target=linux-riscv64`.
That command was tried and exited 1 with usage listing only Linux AArch64
and x86-64. The experimental successes below are evidence for implementing
that port, not a claim that the normal build command or QOS Portable works
on this board already.

## Machine and image

- Pine64 STAR64 at `192.168.0.151`, four SiFive U74 application cores.
- Linux reports ISA `rv64imafdc`, Sv39 virtual memory. No RISC-V Vector
  extension is reported; vector-library checks below used scalar code.
- CPU maximum frequency reported as 1,500,000 kHz, governor `ondemand`.
- Linux 5.15.131, Buildroot 2026.08; the image SHA-256 remains
  `94b1ef9b033eab5e1a2a82557034ae2ecdf10405ef4c5c85b4aa347d98f04d09`.
- The working microSD Express card/UGREEN reader combination was used.
- Cross compiler: Buildroot GCC 14.4.0, `-march=rv64gc -mabi=lp64d`.
  The binaries are native RISC-V ELF64 with the double-float ABI and
  `/lib/ld-linux-riscv64-lp64d.so.1` dynamic loader.

The image is deliberately small: the root filesystem is about 488 MiB,
with 102 MiB used and 349 MiB available. The rest of the 256 GB card was not
allocated to the root filesystem. GCC, Python, Node, Lua, Perl and make were
not found on the board; this check built programs elsewhere rather than
installing development tools or changing the image.

## Memory measurements

Linux reported `MemTotal: 3961604 kB`, about 3.78 GiB usable RAM, with no swap.
At the initial check, BusyBox `free -m` reported 83 MiB used and 3744 MiB
available. After the tests and temporary-data cleanup it reported 82 MiB used
and 3741 MiB available. Probe executables totaling 3.8 MiB remain in `/tmp`.

Per-process values below are peak resident memory from Linux `getrusage` /
`/usr/bin/time -v`, not virtual address-space reservations or FP heap limits.

| Workload | Peak resident memory | Result |
| --- | ---: | --- |
| FP-RISC hello, one/four harts | 1.61 / 1.84 MiB | Printed the expected `42` |
| FP-RISC captured vector map/filter and wide records | 3.88 MiB | Exact expected sums, counts and zero reported pool growth |
| FP-RISC four-worker actor message stress | 2.52–2.78 MiB across four-hart runs | Exact checksum every run |
| FP-RISC 12-million-element linked list | 551.14 MiB | Correct sum; 2.58 seconds guest elapsed |
| Same list with a 64 MiB FP heap cap | 64.65 MiB | Expected named `heap exhausted` panic, exit 1 |
| C++17, one-million-element integer vector plus threads | 9.97 MiB | Correct sum, atomic count and caught exception |
| Software EGL pixel-readback check | 63.88 MiB | Passed in 0.18 seconds |
| Native C RAM/CPU/filesystem/network checker | 257.34 MiB | All checks passed; buffers deliberately total 256 MiB |

The large FP test reserved a 1 GiB FP heap and was bounded by a 1.25 GiB
process address-space limit and a 45-second CPU limit. The 64 MiB negative
test limits the FP heap, not the entire process's RSS. Small tests used a
256 MiB FP heap cap; their resident usage stayed much smaller.

## Native Linux checks

The reusable source is
[`star64-linux-check.c`](../tools/buildroot/star64-linux-check.c). It uses a
90-second watchdog, a 512 MiB address-space limit, 256 MiB of test buffers,
one temporary 8 MiB file on the root filesystem, and loopback TCP. It never
opens a raw device. The temporary filesystem file was deleted after checking.

- Three runs of a deterministic 32-million-step integer recurrence agreed
  across one and four worker threads. Hash `939035ea55a6089a` also matched a
  separately compiled native ARM64 control on the build VM.
- Four pthread workers completed 2,000,000 atomic increments exactly.
- Double-precision arithmetic produced pi `3.141592653589764` within the
  required tolerance; square-root verification passed.
- Both 128 MiB buffers passed all-ones, alternating-bit and address-derived
  patterns, including a copy and complete word-by-word readback. This samples
  256 MiB; it is not an exhaustive test of the board's RAM.
- An 8 MiB SD-filesystem write, `fsync`, rewind and exact byte readback passed.
  Write plus flush took 0.425 seconds. The read can be cached, so this does
  not measure raw-card read performance.
- A 4 MiB loopback TCP transfer passed its checksum check.

The CPU recurrence took approximately 0.140 seconds for one worker and
0.134 seconds for four workers each doing the same amount of work. This
shows useful parallel execution of four times the work. These are short
functional timing samples under an ondemand governor, not a standardized
CPU benchmark or a precise scaling measurement.

The separately built C++17 program passed standard-library vector/iota/sum,
four `std::thread` workers, 400,000 atomic increments, and exception unwinding.

BusyBox shell, awk, tar, gzip/gunzip, SHA-256 and wget were present. A 16 MiB
gzip/decompression round trip produced matching SHA-256 hashes. A 32 MiB
SSH upload over real Ethernet also matched its expected SHA-256. The latter
took 12.05 seconds, about 2.66 MiB/s including SSH setup, encryption and
board hashing; compression was disabled. This is an end-to-end SSH result,
not a raw gigabit Ethernet bandwidth measurement or a diagnosis of its limit.

Software EGL/GLES passed again with Mesa 26.1.8 `softpipe`, EGL 1.5 and
OpenGL ES 3.1. No accelerated PowerVR rendering was enabled or tested.

## FP-RISC experiment

A committed FP-RISC source snapshot at
`74c015bf4ea6ae242ba548187ce5d4ed14b7337f` was copied into the ignored test
directory. The working FP-RISC checkout, including its pre-existing local
changes, was not modified. The compiler binary used for this experiment had
SHA-256 `88bde31f7cf8a50fcb2f51c894d1159e2f988c98a08dbdcc8d2eedeed56219d5`;
the emitted unit cache tag used codegen revision 40.

The experimental path was:

1. Emit scalar RV64 Base-profile assembly using `fpr compile
   --system=bare-metal --profile=base --target=rv64 --float-abi=hard`.
2. Rewrite generated hart-pointer reads into RV64 local-exec TLS loads of
   `fpr_posix_hart`. Linux's `tp` remains libc's thread pointer.
3. In the copied runtime header, use an inline TLS read that obtains the
   current thread's hart without carrying a TLS address across actor migration.
4. Supply an RV64 Linux context switch preserving integer callee-saved
   registers and `fs0`–`fs11`, with 28-word contexts. It leaves process `gp`
   and thread `tp` in place. Initialize the entire expanded context.
5. Cross-link that assembly with the existing POSIX/Unix C runtime and glibc,
   producing ordinary Linux executables, with a four-hart compile cap.

This bypasses the unsupported stock target selection. It does not implement
the proper compiler target, cross-build integration, shared-module relocation
support, QOS Portable application loading, or a complete RV64 ABI/runtime
regression suite.

The following ran with both `FPR_HARTS=1` and `FPR_HARTS=4`:

- Hello/printing; F64/F32 arithmetic, IEEE values, conversions and rendering.
- Captured vector map/filter and nine-field record kernels, with exact
  expected results and reported pool-growth checks.
- Actor echo/state/message/kill example; a custom four-worker actor checksum
  test; sleep/wake under continuing message traffic.
- File write/append/read/exists; stdin lines and stderr.
- Arguments, environment variables and expected process exit status 3.
- Standard-library module use.

Additional four-hart runs checked a three-second sleeping actor, the large
list, the expected heap-cap failure, and four extra repetitions of the custom
actor test. Each custom run exchanged 20,000 requests and 20,000 replies.
All **27 of 27** invocations matched their output and expected exit status.
The expected nonzero exits are counted as successful contract checks.

## Post-test state and evidence

The complete kernel log after testing was identical to the saved pre-test
log: no additional kernel messages, including no new L2-cache, storage or OOM
messages. The two early L2-cache messages and other boot findings from the
[hardware boot record](2026-10-13-STAR64-HARDWARE-BOOT.md) remain unexplained;
this short test does not resolve them or establish long-term stability.
The thermal sensor was readable at the post-test check and reported 53.661 C;
this is one reading, not a recorded peak temperature.

Temporary test data was removed. The native and FP executables remain under
`/tmp/star64-tests-20261013/` until reboot; for example:

```sh
FPR_HARTS=4 FPR_HEAP_MB=256 /tmp/star64-tests-20261013/fpr/hello
```

No image reflash, permanent runtime installation, network configuration change
or service startup change was performed for these tests.

Local logs, executable archive, isolated sources and adapter are preserved in
`.qos/star64/2026-10-13-hardware-tests/`. Key files are `native-check.log`,
`cpu-reference.log`, `cpp-check.log`, `fp-results.json`, `fp-run.log`, per-case
logs, `stock-build.log`, `fp-link.log`, `network-check.json`, `post-tests.log`,
`final-memory.log`, `dmesg-after.log`, and `summary.json`. The experimental
scripts and changes are `prepare-fp.py`, `build-fp.py`, `run-fp.py`,
`runtime-adapter.patch` and `ctx_rv64_linux.S`.
