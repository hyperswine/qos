# Raspberry Pi 4 boot timing and driver/service audit

Kind: implementation, physical measurements and audit. Updated 2026-10-14.
Applies to the Pi 4 appliance; STAR64 is unchanged. Builds keep the installed
ABI 19.41 host, Main and plugins. No kernel rebuild or driver removal was made
for these measurements.

## Nonblocking networking and SD-first boot

The previous Ethernet DHCP client waited through its first attempt before
backgrounding. S41wifi likewise used `udhcpc -b -t 3 -T 3 -A 10`, which holds
startup through its initial attempts. With S99qosp following these services,
the GUI host waited for networking even though its local shell can start offline.

The Pi-specific overlay now provides manual Ethernet ifup/down hooks and
`/usr/libexec/qosp-dhcp`. BusyBox start-stop-daemon detaches a persistent
foreground udhcpc client immediately and records its PID. Startup acknowledges
the process, not a lease. Both Ethernet and Wi-Fi keep retrying while QOS starts.
Search/domain and static-route DHCP options, hostname, lease renewal and the
standard DHCP event script remain enabled. Stop is bounded and checks the
PID and executable before signalling it. The client releases its lease on exit.

The existing S40network/S41wifi/S99qosp order is retained. In reverse shutdown,
QOS therefore drains before networking stops. mdev, the splash and recovery
console keep their existing positions. The new Pi overlay is selected after
the shared overlay; private provisioning should follow both. Disable the
auto-generated `BR2_SYSTEM_DHCP` entry when adopting this overlay in an existing
cached Buildroot configuration.

EEPROM `BOOT_ORDER` changed from `0xf14` (USB then SD) to `0xf41` (SD then USB).
The installed firmware version `57db150d63864d47e6c9071f6b086a5401eb4e92`, all
other configuration and `DISABLE_HDMI=1` were preserved. This avoids trying USB
first on the current SD installation. The official [boot-order reference](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#boot_order)
defines the right-to-left sequence. EEPROM configuration is a board setting,
not part of the ordinary SD image. The exact-version update checksum was
`da2a27671b08c92a970e743ff13bbc257ba44aab67b61ac7582a9f16017126d4`.

## Physical timings

All times below start at Linux's boot clock, excluding the EEPROM/firmware
stage. Process start comes from `/proc/PID/stat` with the kernel's `AT_CLKTCK`
value of 100. Readiness uses the service readiness-file timestamp, adjusted
against real-time and boot-time clocks; the board has no clock adjustment
service in this configuration. It marks Main's declared readiness after graphics
initialization, before the first MVU frame; it is not an external HDMI measurement.

| Milestone | Previous boot | Optimized boot | Repeat normal boot |
| --- | ---: | ---: | ---: |
| Splash start | 3.83 s | 3.80 s | 3.84 s |
| QOS process start | 16.520 s | 4.690 s | 4.730 s |
| QOS readiness | 19.976 s | 8.164 s | 8.192 s |

Readiness improved by 11.8 seconds, about 59%. The SD-first benefit before
Linux starts is additional but was not timed. The first optimized boot applied
the EEPROM configuration; the repeat boot followed removal of completed
update files. Its boot ID was `9b7d5a0b-f303-4b2b-98d8-72fc8336c57c`.
Both boots reached Main and its four plugins, V3D EGL, 1024x600 KMS scanout,
the QOS splash, router DHCP at `192.168.0.233` and authenticated Wi-Fi SSH.
Ethernet was unplugged, so a physical Ethernet lease/hotplug check remains
unverified; the client stayed running without a carrier and did not hold boot.

The helper passed tests with BusyBox and a real process that never acquired a
lease: immediate launch (0.006 seconds), duplicate start, stop, repeated stop,
restart and invalid-interface refusal. The same launcher started/stopped the
real DHCP client on the Pi's unplugged Ethernet interface. The generated
ifup commands were checked without executing them against active networking.
The existing splash policy/rendering check and shell syntax checks pass.

The rebuilt private SD image is `.qos/boot-speed/sdcard.img`, SHA-256
`f45f4489b9ccbdd43eff698f2ae50a99127eb8f79501887dcffbe4254001c5c7`.
It includes the Pi networking overlay but no pending EEPROM update files.

Rollback files are under `/root/qosp-before-fast-boot-20261014`: original
interfaces, Wi-Fi script, EEPROM config and rollback image. Restore networking
files and remove the new DHCP helper when undoing this change. EEPROM rollback
needs a freshly generated checksum/timestamp `.sig`; it retains the quiet
screen setting and restores USB-first boot. Completed update files were saved
there and removed from the boot partition after configuration verification.
Private credentials and the persistent Main disk were not replaced.

## Driver and service candidates

This is an audit of the current shell, not a promise that unused capabilities
can be removed without later hardware tests. No candidates below were removed.

| Candidate | Current evidence | Listed footprint / next step |
| --- | --- | --- |
| Pi camera, ISP and hardware video codecs | bcm2835 camera/codec/ISP, rpivid and supporting video modules load and create numerous video devices; QOS has no open video descriptors | Loaded media-module group totals 824 KiB; module files under drivers/media occupy about 3.7 MiB. Consider a kernel fragment excluding camera/MMAL/codec paths while preserving VC4/V3D graphics. |
| Bluetooth | hci_uart, btbcm and bluetooth load; Broadcom HCD firmware is missing and no Bluetooth daemon runs | Listed Bluetooth/crypto modules total 776 KiB, excluding shared rfkill. Candidate if Bluetooth keyboards/audio are not required; use the matching DT overlay and kernel configuration, preserve serial console and Wi-Fi. |
| Cron | S50crond runs but `/etc/cron/crontabs` is empty | About 223 KiB proportional process memory; an easy optional service removal with a small expected boot benefit. |
| Legacy bcm2835 audio | snd_bcm2835 loads with zero references; QOS currently opens no ALSA devices | 24 KiB listed module allocation. Treat separately from VC4 HDMI audio and possible future headphone support. |
| Generic UIO | uio/uio_pdrv_genirq load with no current user | 32 KiB listed module allocation; retain if later GPIO/FPGA experiments need UIO. |
| General-purpose storage/network filesystems | NFS and NVMe core are built in; iSCSI, RAID, Btrfs and CIFS are configured despite the current SD/ext4 appliance | Smaller future kernel/module set is possible. Keep USB storage/SCSI/UAS if USB boot fallback is desired. Unloaded modules mostly consume SD space, not resident memory. |
| Tracing/debug features | DEBUG_KERNEL, KPROBES, FTRACE, function and function-graph tracers are enabled | Potential kernel-size/initialization reduction; retain the debugging features still useful for this experimental system. |

The media/Bluetooth figures sum `/proc/modules` allocations, not predicted
total memory savings: dependencies and allocator overhead can differ in a
reconfigured kernel. Shared Wi-Fi dependencies such as rfkill/cfg80211 must
remain. The complete compressed module tree occupies about 25 MiB on SD.

Keep mdev, seedrng, SSH, the serial/USB recovery consoles, VC4/V3D, HDMI,
USB/HID, SD/ext4, Ethernet and Broadcom Wi-Fi. Keep the routing sysctls that
ignore interfaces without carrier; they prevent an unplugged Ethernet route
from breaking wireless SSH. Syslog/klog are useful for validating this
experimental board and are not a significant measured boot delay here.

The card is currently negotiating DDR50, 50 MHz, four-bit, 1.8 V operation.
The root filesystem mounts around 1.95 seconds into Linux. There is still
about 3.5 seconds between QOS process launch and readiness; profiling that
application/storage/graphics work and targeted driver coldplug would be more
informative than attributing all remaining time to SD throughput.
