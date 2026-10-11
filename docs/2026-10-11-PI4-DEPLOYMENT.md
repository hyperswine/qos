# Pi 4 deployment of the Qlog and memory fixes, 2026-10-11

The tested Main archive was installed and verified after reboot at
`/usr/share/qosp/app.qa` on the physical Buildroot Pi. The subsequent network
interruption leaves its current running state unconfirmed. This follows the
[Qlog memory investigation](2026-10-11-QLOG-MEMORY.md).
QOS source is `dbc47be0259c0347a8fe7ab3bf2f5c25187e2955`; its FP-RISC pin
is `4f621a38ac02588a72ec1b6a2fa57a2a0b25ff4f`. Both were verified pushed
before deployment. The Portable host, kernel, drivers and onboard app archives
were retained; Main contains the new Qlog, Files, lifecycle, scoped MVU,
Graphics owner and runtime repairs. This was an application deployment,
not a newly flashed SD image or native ARM QOS kernel.

## Installation and rollback state

The old production service stopped with storage drained/flushed and
`shutdown complete`. There were no remaining QOS applications, test runners
or DRM clients. The stopped application's archive and final durable disk
were copied to `/var/lib/qosp/deployment-dbc47be/` before installation:

| Artifact | SHA-256 |
|---|---|
| `app.qa.before` | `d8c9091f65d95a35f464ecbbddf92854dc6cc760b45f07383c1e5f6d87938566` |
| `Main.disk.before` | `62c67b5f7e685a91d1469194834d90a522df3ef883e04e9b83da7de450220d81` |
| Installed new `app.qa` | `eb7d39b7d7717cca3fd4289ce550efc5850fb13c81751e460895ea008a0861ad` |
| Retained `/usr/bin/qosp` | `d900c6f334994b6c59826379be20aba1ccf2f3b4330db2efd95aab6061f0dc4d` |

The archive was staged, checked against the exact successful soak artifact,
then installed by an atomic rename and synced. `/var/lib/qosp/Main.disk`
was preserved: its hash remained identical after UI checks and a reboot.
The original four onboard applications still load from that disk.

To roll back the application, stop `S99qosp`, copy `app.qa.before` to
`/usr/share/qosp/app.qa.new`, set mode 0644, rename it over `app.qa`, sync,
then start the service. The disk backup is available separately; restoring
it would discard any user changes made since deployment and was not done.

## Hardware UI checks

On the existing boot, the installed new Main ran with four workers and a
temporary controlled keyboard FIFO. It used real V3D 4.2.14 / OpenGL ES 3.1
(Mesa 24.0.9) through EGL, with DRM scanout on `/dev/dri/card1` at 1024×600.
The 960×600 shell frame is centered on that display.

Automated key events exercised both home pages, the onboard browser,
resolving `/services/log`, Files, the onboard Clock and Logs, then returned
home. Seven 960×600 RGB screenshots passed size, nonblank/label and distinct
view checks; home, resolved browser and Clock were also visually inspected.
There were no panic, heap-exhaustion or double-resume reports. Main then
stopped with exit success, `stopped` service state and `shutdown complete`.

The Pi was rebooted after this validation. SSH returned, the normal boot
service launched the new archive with zero restarts, and Main reached
`Main Profile ready (8 shortcuts, 2 pages)`. It detected the Logitech K400
Plus at `/dev/input/event2` and the mouse at `/dev/input/mice`, with no FIFO
override. A screenshot key injected through the actual keyboard evdev device
produced exactly the same home pixels as before the reboot. This verifies
the normal evdev path; it does not claim a human physically pressed a key.

## Memory and GPU observation

The intended five-minute production observation **did not complete**. Five
samples covered 122.4 seconds of observation (through Pi uptime 180.5 s), then
the next SSH connection timed out. No successful completion file was produced.
RSS was 42,876 / 42,884 / 45,156 / 45,424 / 45,424 KiB: a step associated with
the screenshot, followed by a short plateau. The same PID 296 and zero service
restarts were recorded in every successful sample. GPU bin/render submissions
advanced to 3,639, with 21 BOs / 7,660 KiB in the final sample. Sampled peak
temperature was 57.939°C.

Subsequent Ethernet and Wi-Fi connections timed out. The Mac could still reach
the router; local subnet discovery found neither known Pi MAC address. This
does not distinguish power/cabling loss from a board/kernel/network failure.
Physical-state clarification was requested. The final planned stop/start
check has not been performed, and current Pi readiness is unconfirmed.

Raw private evidence is in
`.qos/pi4/validation/deployment-dbc47be/`: deployment and shutdown logs,
backup hashes, UI assertions/screenshots, fresh-boot records, smaps, GPU
counters, temperatures and service samples.

Before reboot, even with every QOS process stopped and no DRM clients,
V3D reported 29,750 BOs / 1,122,632 KiB. After reboot with the new Main
running, that fell to **20 BOs / 5,408 KiB**. A screenshot added one buffer
and increased the total to 7,660 KiB. Reboot clears the old retained baseline;
these observations do not establish its original cause.

The governor remained powersave at 600 MHz. The storage stress suite already
passed on this board in the preceding investigation; the remaining roughly
25 MiB per-workload global block actor-identity growth is not fixed by this
deployment. Overnight endurance and physical power-loss tests remain open.
