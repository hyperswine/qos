# STAR64 RISC-V module loading backport

Kind: implementation and physical hardware validation record.
Date: 2026-10-15. Applies to Pine64 STAR64 vendor Linux 5.15.131 from
Fishwaldo/Star64_linux commit 1456c984f15e21e28fb8a9ce96d0ca10e61a71c4,
built with Buildroot 2026.08 GCC 14.4.0. Display and keyboard disconnected.

This follows [the boot timing investigation](2026-10-15-STAR64-BOOT-TIMING.md).
Its slow loader algorithms were still present after nonblocking networking.
The new kernel keeps the existing vendor drivers, device tree, configuration,
PowerVR firmware/userspace and Wi-Fi provisioning. No storage was reflashed.

## Changes

The STAR64 global Linux patch directory now contains two narrow backports:

- `0001-riscv-module-cache-hi20-search-position.patch`: remember the last HI20
  relocation match and wrap the next search safely instead of restarting at
  entry zero. Based on upstream [080c4324fa5e](https://github.com/torvalds/linux/commit/080c4324fa5e81ff3780206a138223abfb57a68e),
  including the subsequent [bounds fix](https://git.kernel.org/riscv/c/0b4cce68efb9).
- `0002-riscv-module-sort-plt-got-counting.patch`: filter relevant relocations
  into a scratch buffer, sort it and count adjacent duplicates. Based on
  upstream [be17c0df6795](https://github.com/torvalds/linux/commit/be17c0df67959fe4f88dac75dc26ed9252d4b133).
  The adaptation retains this 5.15 kernel's per-section totals and existing
  supported relocation types. It allocates once per section through the 5.15
  kvmalloc_array API, frees scratch storage and returns ENOMEM on failure.
  It does not reorder the original relocations or need kvrealloc.

The new Image's SHA256 is
`940e0e8068d326ddbb711ad241b21a9cdec6dd49bdded5e37c54fa85993f8b91`.
Its version is Linux 5.15.131 #3 SMP Thu Oct 15 11:05:41 UTC 2026.
The original /boot/Image remains intact, with SHA256
`fa5212db039b1e62b14eac585ba5f31c01d7a0017f92ced73ce6f089e1273465`.

## Validation before hardware boot

Both patches apply without fuzz to the pinned vendor sources. The rebuilt
kernel's .config matches the original exactly, including compiler identity.
The existing modules still use the same 5.15.131 release/ABI.

`tools/buildroot/star64-loader-check.py --kernel /path/to/patched/linux-custom`
extracts the actual changed functions and compiles them with address/undefined
sanitizers and userspace shims. It checks original PLT/GOT counts, unchanged
relocation order, extreme addends, allocation failure and empty sections;
HI20/LO12 I/S and GOT pairing, shuffled relocation order, backward wrapping,
a match at the final entry, and missing-match rejection. All checks passed.

The rebuilt Image booted the existing STAR64 rootfs under QEMU virt. Explicit
modprobe of both 8852bu and pvrsrvkm passed, as did the normal QEMU check's
software EGL pixel readback, SSH listener/configuration and emulated Ethernet
DHCP. QEMU does not emulate the board's physical Wi-Fi or PowerVR device.

## Guarded physical boot

The candidate was installed separately as `/boot/Image-loader-fast`; the
original `/boot/Image` and DTB were not replaced. A one-shot test entry used
`init=/root/qosp-loader-test/init panic=10`. Before any module coldplug, this
wrapper restored the original extlinux configuration to disk and started a
hardware watchdog feeder. Without confirmation, it stops feeding after 180
seconds; the watchdog's 60-second timeout then resets into the original kernel.
This recovery covers module loading after userspace init, not an early hang
before the wrapper runs. The watchdog's arm/disarm path was checked first.

The physical test boot recovered wireless public-key SSH at 192.168.0.215,
reported Main ready and initialized the PowerVR B-Series BXE-4-32 EGL renderer.
The original boot configuration had been restored correctly. The watchdog was
confirmed and disarmed, and its inactive state was checked before promotion.

| Milestone | Guarded test, Linux boot clock |
|---|---:|
| Watchdog enabled, before module loading | 5.976 s |
| 8852bu staging warning | 7.880 s |
| 8852bu entry function called | 8.032 s |
| Wi-Fi USB driver registered | 8.429 s |
| QOS process started | 11.700 s |
| QOS ready | 14.740 s |
| wlan0 link/association ready | 17.397 s |

The warning-to-entry gap fell to 0.153 s, versus 13.361 s in the earlier
instrumented boot; the original uninstrumented boots showed about 24 s.
The roughly 0.4 s hardware probe remains. This is a physical result, unlike
the earlier userspace relocation benchmark. Wi-Fi association/DHCP happens
later in parallel with QOS. These timings exclude SPL/OpenSBI/U-Boot and do
not measure the first visible HDMI frame.

## Normal boot after promotion

A second physical boot used the normal fast-kernel entry, without the test init
wrapper, initcall debugging or a running userspace watchdog helper:

| Milestone | Normal boot, Linux boot clock |
|---|---:|
| /sbin/init started | 5.831 s |
| PowerVR kernel driver ready | 7.097 s |
| 8852bu staging warning | 7.738 s |
| Wi-Fi USB driver registered | 8.289 s |
| QOS process started | 11.800 s |
| QOS ready | 14.480 s |
| wlan0 link/association ready | 17.671 s |

Wireless SSH recovered at 192.168.0.215; Main and the PowerVR EGL renderer were
ready, with zero service restarts. The watchdog was inactive and initcall_debug
was N. Both kernel hashes matched their saved values. QOS readiness is now
14.5 seconds versus 40.8–48.4 seconds with nonblocking networking but the old
loader, or 63 seconds before either optimization. The normal Wi-Fi warning to
registration interval is 0.551 seconds, including its hardware probe.

Boot IDs: guarded test d82ccd89-50a6-4149-afa7-24483bcabffb; normal boot
76adafe1-572c-40a7-a219-5146a3cedec9. Logs are locally ignored as
`.qos/star64/loader-fix/physical-test.log` and `normal-boot.log`.

No HDMI/input behavior was physically inspected because the board is headless.
An Ethernet DMA initialization failure still occurred on one port; this vendor
issue was also present before the loader patch and was not changed here.

## Installed state and recovery

The normal extlinux configuration selects `star64-fast`, pointing at
`/boot/Image-loader-fast`, and retains `star64-known-good`, pointing at
`/boot/Image`. The normal entry omits the test init wrapper and debug settings.
The test helper is not a permanent service or watchdog daemon.
Original config and test records are under `/root/qosp-loader-test`; the original
kernel and boot configuration were also copied to ignored local files under
`.qos/star64/loader-fix/`. Source patches and checks are tracked repository files;
logs, private rootfs and kernel binaries remain ignored local artifacts.

To restore the original default remotely while SSH is available:

```sh
cp /root/qosp-loader-test/extlinux.original.conf /boot/extlinux/extlinux.conf.next
mv /boot/extlinux/extlinux.conf.next /boot/extlinux/extlinux.conf
sync
reboot
```

With a mounted SD root partition, restoring the same original boot config also
selects `/boot/Image`. Retain both kernels until satisfied with hardware tests.

The Buildroot source recipe includes these patches automatically on a fresh
kernel build. An already-patched/cached output needs a clean kernel rebuild
when applying new patches (linux-dirclean, then the regular STAR64 build).
The running board received the new kernel directly; a complete replacement SD
image has not been rebuilt in this task.
