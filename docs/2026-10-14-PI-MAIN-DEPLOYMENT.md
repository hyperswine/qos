# Matching Main deployment and remote Pi assessment

Kind: deployment record. Checked 2026-10-14 on the physical Pi 4 over SSH.

## Installed revision and state

Deployed normal `programs/main.fpr`, the Portable ES host, seed disk and all
four onboard archives (`clock`, `logs`, `browser`, `disk`) together:

- QOS: `b67f426c470b12f2cc27fd8e8d47cdebf303607c`.
- FP-RISC: `aee3e962c8c3f2d6d4967a35e035856258de5ce6`.
- No diagnostic Main, storage fault-injection or graphics profiling flags.
- Existing CPU policy remains `powersave`, sampled at 600 MHz.
- No OS reboot, kernel, bootloader or network configuration change.

The writable disk upgrade preserved all ten existing committed records
byte-for-byte and the app index, then appended the four matching archives.
The log head moved from 1081 to 2469 and the stable generation from 5 to 7.
Both fallback superblocks publish the updated bundle. The updater's ten
regression checks passed before preparing the candidate.

| Installed artifact | SHA-256 |
|---|---|
| `/usr/bin/qosp` | `37a5ef2969af08c3c665bf43699bd25ccfca209ce639432cb634db1d95651dbe` |
| `/usr/share/qosp/app.qa` | `e147f2a2e103f8901a1879fec9156a17e78f743b54dad36d16bb3992df27cf0d` |
| `/usr/share/qosp/Main.disk` | `f315e4a6b6bb0175c8353d31a821b12a56732b1711a890ac70305882a26c2dac` |
| `/var/lib/qosp/Main.disk` after assessment | `cea8d40ae71411ea970112aacb3eaa2f43b35e77ecbe58d931de5b8b17ebae1a` |

The complete archive manifest and raw evidence are retained locally under
`.qos/validation/pi-main-deployment-20261014/` (ignored by Git).

## Validation on the Pi

Before replacing the installed session, the production candidate ran against
an upgraded isolated SD-backed disk at 1024×600. Four interaction cycles
completed in 88.88 seconds, followed by normal quit with storage drain. A
second boot passed graceful SIGTERM shutdown in 30.07 seconds. Neither path
needed forced termination; the original installed process stayed unchanged
through preflight.

The installation stopped the supervisor cleanly, verified a fresh stopped disk
snapshot against the preflight input, retained rollback files, replaced the
host/shell/seed/writable disk while stopped, verified hashes and started Main.

The installed GUI was then exercised on the real KMS display using temporary
private evdev FIFOs. Captures read the framebuffer selected by the active CRTC,
not an offscreen rendering. Results:

- HDMI `card1-HDMI-A-2` connected at 1024×600; scanout on `/dev/dri/card1`,
  EGL 1.4 with V3D 4.2.14 / Mesa 24.0.9.
- Home rendered its responsive three-column layout and visible focus outline.
- Touch press alone did not launch; SYN_DROPPED cancelled a captured tap;
  a fresh release opened Clock, whose displayed time subsequently changed.
- Files scrolled with Page Down; Refresh, Tab, Shift-Tab and Home navigation
  completed. All four onboard apps opened and rendered.
- Changing focus cancelled Browser's captured row. Browser read `/logs` and
  displayed actual service startup text.
- Two further rounds of closing/reopening all four apps completed with no
  automatic supervisor restarts.

Temporary replay input was removed from the running configuration afterwards.
The final service uses ordinary device discovery, and `/etc/default/qosp`
retains only its existing splash export. No physical keyboard, mouse or touch
input was discovered in this session; replay validates software input handling,
not delivery from a physical touch controller.

A final read-only 300.84-second observation sampled the normal installed
process eleven times. PID 10528 remained ready throughout, with zero automatic
restarts. RSS ranged from 61,796 to 62,304 KiB (60.35–60.84 MiB), a 508 KiB
increase. Temperature ranged from 51.121 to 52.095°C. All frequency samples
were 600 MHz. Global GPU BO diagnostics were unavailable, so this record makes
no GPU-memory claim. This short observation does not establish long-term
memory stability. Manual supervised restarts used during acceptance are
separate from the automatic restart count.

The boot ID stayed `9bf8713b-511d-481c-976b-9f459a08ac86`. The filesystem had
76.6 MiB free after installation and rollback retention.

## Remaining visible issue and physical boundary

The onboard Clock app updates its time but continues to show “Loading…” while
polling. In `programs/mods/clockapp.fpr`, each refresh sets the phase to Loading.
A follow-up should preserve a successful cached display during background
refresh while keeping initial loading and actual service errors explicit.
This is a UI status issue observed in the deployed matching revision.

KMS captures prove the pixels selected for HDMI scanout. They do not prove
panel backlight, physical appearance or actual touch/keyboard operation while
nobody is near the Pi. The final capture is `observed-home.png` in the local
evidence directory; individual app and interaction captures are retained too.

## Rollback

The Pi retains the stopped original host, shell, seed, writable disk and service
configuration in `/var/lib/qosp/deployment-gui-20261014/original.tar.gz`, with
hashes and a rollback script. To deliberately restore that deployment on the Pi:

```sh
/var/lib/qosp/deployment-gui-20261014/rollback.sh
```

The script stops Main, restores the archive, flushes storage and starts Main.
Restoring its writable disk also discards writes made since this upgrade;
retain a fresh stopped snapshot first if later user data must be preserved.

See [physical Pi tools](../tools/pi4/README.md) for the disk upgrade workflow
and framebuffer readback helper, and [GUI performance](2026-10-14-GUI-PERFORMANCE.md)
for the preceding timing and application-lifetime validation.
