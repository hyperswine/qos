# QOS Portable image: memory and speed measurements

Kind: dated implementation/measurement record. Date: 2026-09-22.
Added in 3374437 on 2026-09-22; memory measurements explicitly dated 2026-09-21.
Extracted without reconciling historical claims on 2026-09-29 from
[IMAGE.md](2026-09-21-IMAGE.md). No historical checks were rerun.

## What it costs in memory

Measured 2026-09-21 on the QEMU target (Linux 6.12, 4 CPUs, 2 GiB), with
`/proc/meminfo` after `drop_caches`, against the Ubuntu 24.04 cloud image
`tools/arm64-vm` boots (same RAM, same CPUs, idle):

| | Buildroot image | Ubuntu 24.04 server |
| --- | --- | --- |
| occupied at idle, of 2 GiB (physical − MemFree) | ~97 MiB | ~257 MiB |
| of which the kernel reserved at boot | 55 MiB | 93 MiB |
| user processes (AnonPages) | 3 MiB | 28 MiB |
| kernel slab | 10 MiB | 45 MiB |
| page cache that survives `drop_caches` | 7 MiB | 41 MiB |
| processes, kernel threads included | 76 (10 in userspace) | 110 (12 running services) |
| root filesystem | 35 MiB | 28 GiB (with the toolchain) |
| `qosp` running `interactive_desktop_gl` | +86 MiB RSS | — |

So about 2.6x less at idle, which is much smaller than the disk difference.
An idle Linux is mostly kernel: at boot, before any process runs, 55 MiB is
already gone. What the image removes is systemd, journald, resolved,
networkd and unattended-upgrades (about 25 MiB of processes), the slab those
services keep alive, and nearly all of the page cache. It runs fine in 1 GiB. Most of
`qosp`'s own 86 MiB is Mesa's software rasterizer (`softpipe`) and its
threads. On a Pi, v3d does that work in hardware.

Two things that number depends on:

- **The buddy allocator used to write into the whole plugin window.**
  `buddy_reserve_range` fenced off the 1 GiB window one 64 KiB unit at a
  time, writing a free-list node into each unit: 16,384 writes into memory
  nobody had used. That made every `qosp` process 256 MiB resident on 16 KiB
  pages (macOS), and on this image the whole GiB, so a 1 GiB machine
  OOM-killed the application before it drew anything. It now takes the range
  as whole aligned blocks and writes nothing inside it (`runtime/buddy.c`).
- **Transparent huge pages.** This kernel defaults THP to `always`, which
  rounds every first write in the arena up to a 2 MiB page: the same
  application is 224 MiB with it on and 86 MiB with it off. Ubuntu's default
  is `madvise`. `CONFIG_TRANSPARENT_HUGEPAGE_MADVISE=y` in the kernel
  fragment (or `transparent_hugepage=madvise` on the command line) would
  make it the image's default too.

## What it costs in speed

The same five `.qa` apps (identical machine code; only the arena base differs
on macOS) run under each OS's qosp with `FPR_HARTS=4`, best of three, on one
Apple M4. The three guests each get 4 vCPUs under HVF.

| app | macOS (native) | FreeBSD 14.5 | Ubuntu 24.04 | Buildroot | Buildroot, THP `madvise` |
| --- | --- | --- | --- | --- | --- |
| `bfib`: fib 40, one actor | 1.19 s | 1.10 s | 1.16 s | 1.18 s | 1.12 s |
| `balloc`: 2000 × 40k conses, pool reset per round | 1.00 s | 0.96 s | 1.02 s | 1.27 s | 0.98 s |
| `bpar`: fib 39 on each of 4 harts | 0.84 s | 0.75 s | 0.86 s | 0.87 s | 0.75 s |
| `fanin`: 40 senders through one hub | 0.42 s | 0.49 s | 0.52 s | 0.56 s | 0.57 s |
| `pingpong`: 20k cross-hart round trips with sleeps | 7.90 s | 8.21 s | 9.02 s | 9.59 s | 9.48 s |

Compute and allocation are the same everywhere to within about 10%, which is
what you'd expect: once the app is running it is the same code on the same
cores, and the OS is not involved. Where the OS is involved, it shows:

- **Transparent huge pages cost Buildroot 27% on allocation.** Every pool
  reset hands pages back and the next round faults them in again, and with THP
  at `always` each fault zeroes 2 MiB. At `madvise` (Ubuntu's default) it is
  level with the rest. That is the second reason, after memory, to set
  `CONFIG_TRANSPARENT_HUGEPAGE_MADVISE=y` in the image's kernel.
- **Cross-hart wakes and short sleeps are slower on Linux.** `pingpong` is
  14% slower on Ubuntu and 20% slower on Buildroot than on macOS, with FreeBSD
  in between (4%). THP makes no difference there. It has not been
  investigated; timer slack and the two kernels' configs are the first
  suspects.

Caveats: the guests run under a hypervisor with 4 vCPUs that macOS may place
on efficiency cores, and each number is one app, not a workload.
