# STAR64 nonblocking networking and module loading

Kind: physical board measurement and implementation record.
Date: 2026-10-15. Applies to the running Pine64 STAR64, vendor Linux 5.15.131,
Buildroot 2026.08, RTL8852BU Wi-Fi and the validated PowerVR 1.17 stack.
The display and keyboard were disconnected for these checks.

## Networking change

Both Ethernet interfaces use manual ifupdown hooks that bring the link up and
launch a persistent DHCP client through `/usr/libexec/qosp-dhcp`. The helper
uses `start-stop-daemon` to detach immediately and acknowledge process startup,
without waiting for a lease. It retains a stable PID for duplicate start and
clean shutdown. Clients continue retrying if a cable or router appears later.

`S41wifi` keeps association in the supplicant's background process and uses the
same DHCP helper for wlan0. Duplicate start reuses the existing processes;
stop waits for the supplicant's interface cleanup before a restart. The Wi-Fi
PID is `/run/star64-wpa.pid`; DHCP now uses `/run/udhcpc-wlan0.pid`, replacing
`/run/star64-wifi-dhcp.pid`. Applying the files live does not migrate an already
running old DHCP process: reboot or stop using the old script before replacing
it and restarting. This board was rebooted after installing the new files.

Driver loading and link initialization are still synchronous. The helper is
identical to the Pi-specific copy, but resides in the STAR64 overlay because
this image does not select the Pi or shared overlays. QOS retains S99 shutdown
ordering and the existing GPU/userspace configuration.

## Physical results

Times below start at Linux boot, excluding SPL/OpenSBI/U-Boot. Readiness is the
QOS readiness file timestamp converted to the boot clock, not a visible HDMI
frame. Startup is the application process's /proc start time (100 ticks/sec).

| Boot | QOS process start | QOS ready |
|---|---:|---:|
| Original networking | 60.050 s | 63.000 s |
| Nonblocking, with stack sampler | 39.860 s | 42.910 s |
| Nonblocking, with initcall timing only | 37.840 s | 40.840 s |
| Nonblocking, normal boot with diagnostics removed | 45.460 s | 48.420 s |

The observed readiness range after the change was 40.8–48.4 seconds, versus
63.0 seconds before it (14.6–22.2 seconds earlier). The final normal boot
started SSH at 45.39 seconds and QOS at 45.46 seconds.
Timing varies with module loading, CPU frequency and storage/cache state; it
is not a promise of a fixed DHCP-only saving. All optimized boots recovered
public-key SSH over wlan0 at the router's current lease, 192.168.0.215, and QOS
reported Main ready plus the PowerVR B-Series BXE-4-32 EGL renderer.

The helper lifecycle check used a client that never obtains a lease and returned
in 0.006 s. Duplicate start, clean/repeated stop, restart and invalid interface
refusal passed. On STAR64, the real eth1 client passed duplicate start, stop,
repeated stop and start with no carrier; duplicate Wi-Fi start retained the
existing supplicant and DHCP processes. Actual Ethernet lease acquisition and
HDMI/input output were not tested in this headless setup.

## What caused the apparent 24-second Wi-Fi delay

The original dmesg gap was from the module staging warning at 13.606 s to USB
driver registration at 38.226 s. That warning occurs before the module's entry
function and cannot be interpreted as the beginning of hardware probe.

A later boot with initcall timing separated these stages:

- Staging warning for 8852bu: 20.598 s.
- Entry function called: 33.958 s.
- USB probe finished: 34.355 s (395116 reported microseconds).
- Entry function returned success: 34.361 s (391740 reported microseconds).

The vendor kernel reports these durations using nanoseconds shifted right by
10, so the wall timestamps are the more direct measure: roughly 0.4 seconds
inside the driver's entry function. Most of the silent interval precedes it.
The first stack sampler found modprobe mostly running rather than sleeping;
one sample caught a module-file read in finit_module. It did not attribute a
precise percentage of time to each kernel routine.

Source inspection found two quadratic algorithms in the old RISC-V module
loader: PLT/GOT duplicate counting in `arch/riscv/kernel/module-sections.c` and
HI20 relocation lookup in `arch/riscv/kernel/module.c`. The 7.3 MiB 8852bu.ko
contains 29738 CALL_PLT relocations and 16957 HI20/LO12 pairs. A read-only native
benchmark replayed these searches using the exact module, without loading it
or changing the kernel:

| Search | Vendor algorithm | Optimized comparison | Equivalent result |
|---|---:|---:|---|
| PLT/GOT duplicate count | 3.122 s, 492469766 comparisons | 0.031 s, filter/sort | 5040 unique entries |
| HI20 pairing | 3.649 s, 571543896 comparisons | 0.0012 s, cached position | same matched relocation index sum |

This establishes substantial avoidable loader CPU work, rather than a
24-second Wi-Fi firmware timeout. The benchmark is not a patched-kernel boot
measurement; its timings do not predict the exact boot improvement. The board
uses the ondemand CPU governor (observed 750 MHz, maximum 1.5 GHz), which can
also affect timings.

Upstream has addressed both areas:

- [RISC-V ELF relocation search discussion](https://lists.infradead.org/pipermail/linux-riscv/2023-May/031863.html).
- [PLT/GOT entry counting optimization](https://lists.infradead.org/pipermail/linux-riscv/2025-April/068849.html), later merged as `be17c0df6795`.
- [Follow-up allocation failure fix](https://git.zx2c4.com/linux-rng/commit/arch/riscv/kernel?id=c42458fcf54b3d0bc2ac06667c98dceb43831889).

A targeted loader backport was subsequently built and tested: see
[the loader fix and physical results](2026-10-15-STAR64-LOADER-FIX.md).
The measurements in this page precede that kernel update. The networking-only
change described here retained the original loader loops. The follow-up tested
the backport with a guarded physical boot and retained the vendor GPU stack,
embedded Wi-Fi firmware and RF calibration.

## Recovery and remaining observations

Original files and evidence are on the board under
`/root/qosp-before-star64-fast-boot-20261015`. Backups are outside `/etc/init.d`
so BusyBox rc cannot execute them. A temporary five-minute automatic rollback
guard covered the first boots and was disarmed after wireless SSH returned.
The S09 diagnostic/guard entry was removed, and initcall debugging was disabled.
Local detailed logs and the benchmark are ignored under `.qos/star64/boot-speed/`.

The kernel still reports an eth0 DMA reset failure during link initialization.
eth1 has no carrier and wlan0 is the active network path. That existing Ethernet
error is separate from the module-loader gap and was not changed here. Missing
Bluetooth/video-decoder firmware also remains; those are not Wi-Fi firmware.

To roll back, stop the new Wi-Fi service while it is still installed, then
restore `interfaces` to `/etc/network/interfaces` and `S41wifi` to
`/etc/init.d/S41wifi` from the backup and reboot. Keep an independent recovery
path when doing this remotely. The new helper can remain unused on disk.

Source overlays and the running board were updated. A replacement SD image was
not rebuilt or flashed as part of this task.
