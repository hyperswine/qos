# A Linux image that exists to run one QOS Portable application

This is a Buildroot external tree. It builds a Linux system with nothing in
it but what QOS Portable needs — a kernel, Mesa, ssh, wifi, and `qosp` — so
that a Raspberry Pi 4 boots straight into an FP-RISC application, full screen,
with no desktop, no compositor and no window system anywhere in the picture.

    qos/tools/buildroot/
      configs/qosp_qemu_aarch64_defconfig   the test loop: QEMU virt
      configs/qosp_rpi4_defconfig           the target: a Pi 4 SD card
      configs/qosp_star64_defconfig         STAR64 Linux bring-up (no qosp yet)
      package/qosp/                         the package that builds qosp
      board/qosp/                           kernel fragment, Pi config.txt
      br.sh                                 build
      boot.sh                               boot the QEMU image
      qosp-check.py                         boot it and assert what came up

The separate [STAR64 bring-up target](board/qosp/star64/README.md) builds
RISC-V Linux with SSH, Ethernet/Wi-Fi support, vendor HDMI drivers and
software EGL diagnostics. Its baseline image does not include QOS or the
PowerVR runtime. QOS Main and hardware EGL/GPU presentation have passed on
the installed board with the optional
[PowerVR bundle](../../docs/2026-10-14-STAR64-POWERVR.md).
The target uses Buildroot 2026.08 in a separate source/output tree.

## Why this is small

`qosp`'s graphics tier (`hal/unix/gfx.c`) was written for exactly this case.
It takes an EGL context on the **surfaceless** platform, renders an ES 3.1
scene into an offscreen FBO, and `drm_scanout.h` puts the frame on the monitor
through a KMS dumb buffer: one `SetCrtc` on the first `/dev/dri/card*` that
has a connected connector.

So the entire display stack is `libEGL` + `libGLESv2` + a DRM device. No X,
no Wayland, no GBM surface, no compositor, no display manager. That is the
whole reason an image like this can be a few tens of megabytes.

Input is the same story: `evdev_raw.c` reads `/dev/input/event*` and
`mice_raw.c` reads `/dev/input/mice`, both of which a bare Linux console has.

## Building

Buildroot does not run on macOS, so build on Linux. This repo already keeps a
VM for that:

    tools/arm64-vm/vm.sh up
    tools/arm64-vm/vm.sh sync

Inside it, once:

    git clone --depth 1 -b 2025.02.x \
      https://gitlab.com/buildroot.org/buildroot.git ~/buildroot

An image hosts **one** application, and which one is the point of the image,
so build that first — `br.sh` deliberately will not guess:

    make -C ~/qos qos-app PROG=programs/terra2.fpr    # writes qos/app.qa

Then:

    ~/qos/tools/buildroot/br.sh qemu        # or: rpi4

Output lands in `~/.cache/qosp-br/<target>/images`. Anything after the target
goes to Buildroot, so `br.sh qemu menuconfig` and `br.sh qemu qosp-rebuild`
work as usual.

### How `qosp` gets built

`qosp` is an FP-RISC program (`qos/portable/qosp.fpr`) whose HAL is the C
under `qos/hal/unix`, and the thing that knows how to assemble those is the
qos tree's own Makefile. So `package/qosp/qosp.mk` **calls that Makefile**
rather than restating its source list — the `portable-es` target, through two
hooks added for this:

| hook | what it does |
| --- | --- |
| `FPRBUILD_EXTRA=--target=linux-<arch> --cc <gcc>` | select the target ISA and link with Buildroot's cross compiler |
| `QOSP_ARCH=<arch>` | decide `-ffixed-x28` by the TARGET, not the build machine |
| `QOSP_ES_OUT=<path>` | write the binary into Buildroot's build dir |

`fpr` itself stays out of Buildroot: it is a Haskell program, it runs on the
build machine, and it only ever emits assembly for the target. Point
`BR2_PACKAGE_QOSP_FPRISC_DIR` at a checkout where `fpr` is already built
(empty means the sibling `../fprisc`, the rule the rest of the build follows).

The build machine may have a different architecture. The package passes
`--target=linux-<arch>` explicitly, selecting generated code, context switch
and ABI flags for aarch64, x86_64 or riscv64. `--cc` alone still changes only
the C compiler. Linux riscv64 uses RV64GC/LP64D; see the
[STAR64 Portable validation](../../docs/2026-10-14-STAR64-PORTABLE.md).

## Booting the QEMU image

From macOS, with the images copied out of the build VM:

    tools/buildroot/boot.sh pull     # rsync Image + rootfs.ext4 out of the VM
    tools/buildroot/boot.sh up       # headless, serial log
    tools/buildroot/boot.sh gui      # ... in a window you can watch

`qosp-check.py` does the whole thing unattended: boots the image, logs in over
the serial console, and asserts that the DRM device is there, that EGL came up
surfaceless, that the scanout engaged and that a frame was drawn.

## The Pi 4

`board/qosp/rpi4/config.txt` carries the one line that matters:

    dtoverlay=vc4-kms-v3d

That is what hands the display to the open vc4 KMS driver, so Linux exposes a
`/dev/dri/card*` **with a connector** — which is what the scanout probes for.
Without it the Pi has a framebuffer and no DRM device, and `qosp` renders
offscreen into nothing anyone can see. Mesa's `v3d` (3D) and `vc4` (display)
gallium drivers are both selected; `v3d` is a render node with no connectors
and the scanout probe skips it by design.

The other Pi-specific decision is **how drivers get loaded**. The bcm2711
defconfig ships `vc4` and `v3d` as modules, which is right for a distribution
with udev and wrong here twice: device creation is devtmpfs, so nothing would
load them at all and the image would boot to no `/dev/dri`; and even with
`mdev` loading them it would be a race, because `S99qosp` starts the
application at boot and a display that appears a moment later is one the
scanout probe has already missed. So `board/qosp/rpi4/linux-kms.fragment`
builds them in, and the card is there before userspace is. `mdev` is enabled
as well, for everything that legitimately arrives later — the Broadcom wifi
module, and anything plugged in after boot.

`br.sh rpi4` writes `images/sdcard.img`, which is a whole card:

    # pick the right disk very carefully
    diskutil list
    diskutil unmountDisk /dev/diskN
    sudo dd if=sdcard.img of=/dev/rdiskN bs=4m status=progress
    diskutil eject /dev/diskN

## Logging in, ssh and wifi

The image ships OpenSSH, `wpa_supplicant` and `iw`, and configures **none** of
them — credentials are not something a repo should invent.

The unprovisioned image has an empty root password, so the **serial console** logs in with `root` and
Enter. `sshd` refuses empty passwords, so before ssh works you must either set
a root password (`BR2_TARGET_GENERIC_ROOT_PASSWD` in `menuconfig`) or add a
public key through a rootfs overlay (`BR2_ROOTFS_OVERLAY`).

For wifi, write `/etc/wpa_supplicant.conf` on the target — `wpa_passphrase` is
in the image for that — and bring it up with `wpa_supplicant -B -i wlan0 -c
/etc/wpa_supplicant.conf && udhcpc -i wlan0`. The Pi's onboard Broadcom
firmware (`brcmfmac_sdio-firmware-rpi`) is already installed.

### Provision a headless Pi before flashing

On the Mac, put `SSID` and `PASSWORD` in the ignored `qos/.env`, then run:

    python3 tools/buildroot/provision-pi.py --country AU
    python3 tools/buildroot/provision-check.py

This generates `.qos/pi4/overlay` with a WPA2 Personal configuration and your
`~/.ssh/id_ed25519.pub` as root's authorized key. `--authorized-key`, `--env`,
`--hostname` and `--output` override the defaults. The parser treats values
as data, derives the WPA2 PSK, and never prints credentials. WPA3-only and
enterprise Wi-Fi need a different supplicant configuration. The generated
overlay and resulting image contain network access material; keep them local.

`vm.sh sync` deliberately excludes `.env` and `.qos`. Copy only the generated
overlay into `~/qos/.qos/pi4/overlay` in the Linux build VM, then set
`BR2_ROOTFS_OVERLAY` in that target's `menuconfig` to these directories:

    $(BR2_EXTERNAL_QOSP_PATH)/board/qosp/overlay $(BR2_EXTERNAL_QOSP_PATH)/board/qosp/rpi4/overlay /home/dev/qos/.qos/pi4/overlay

The first is shared setup, the second is Pi-specific networking, and the last
is private settings. The Pi defconfig already selects the tracked directories
and leaves `BR2_SYSTEM_DHCP` empty: its overlay supplies Ethernet configuration.
Existing cached target configs
must be updated explicitly: `br.sh` preserves their `.config`.

`S41wifi` loads `brcmfmac` after the firmware filesystem is available, waits
up to five seconds for `wlan0`, then starts `wpa_supplicant` and DHCP. In the Pi
overlay, `/usr/libexec/qosp-dhcp` backgrounds the persistent client immediately,
including its first lease attempt; Ethernet uses the same launcher through
ifup/down hooks. QOS keeps its existing S99 startup and reverse shutdown order,
so its clean shutdown still precedes network teardown. The shared overlay's
older Wi-Fi fallback waits for its initial attempts before backgrounding;
select the Pi overlay for nonblocking networking. Stop waits up to five seconds per daemon before
allowing a replacement to start; the old supplicant can otherwise bring the
new instance's interface down during its cleanup.

On the tested Pi, QOS readiness moved from 19.976 seconds to 8.164 and 8.192
seconds after Linux starts. SD-first EEPROM boot order is a separate one-time
board setting; see the [boot timing and driver audit](../../docs/2026-10-14-PI-BOOT-TIMING.md).

The overlay disables only Broadcom firmware supplicant offload
(`feature_disable=0x2000`, `BRCMF_FEAT_FWSUP` in the pinned kernel). On the
tested Pi 4 / BCM43455, the default offload stalled at `ASSOCIATED`; letting
`wpa_supplicant` perform the WPA2 handshake reached `COMPLETED` and DHCP.
Ethernet remains available. The overlay's `40-qosp-routing.conf`, loaded by
`S02sysctl`, makes IPv4 ignore routes through interfaces without carrier.
On the tested Pi, unplugging Ethernet otherwise left its DHCP subnet route
preferred over Wi-Fi, preventing IPv4 SSH replies despite a working wireless
connection. IPv6 link-local SSH remained reachable during diagnosis.

SSH accepts the
supplied public key and disables password authentication. Host keys are
generated on the device's first boot, not shared between images. Use the
router's DHCP lease for hostname `qosp` to find the address, then:

    ssh root@<pi-address>
    reboot

The minimal image does not include an mDNS daemon; `qosp.local` discovery is
not assumed. `python3 tools/main-profile.py` builds the graphical shell and
onboard apps; select `BR2_PACKAGE_QOSP_MAIN_PROFILE` and its artifact directory
to boot that profile with the supervisor's required readiness signal.

Main's graphics owner is pinned to hart 0: EGL contexts remain current on
their creating OS thread across mailbox waits. An unpinned owner passed
initialization but failed on a later frame under the four-worker scheduler.
`tools/guishell-check.py` now defaults to four workers; `FPR_HARTS=1` remains
available for comparison. See the [Pi 4 hardware validation](../../docs/2026-10-11-PI4-BUILDROOT-VALIDATION.md)
for the tested headless path and remaining boundaries.

## The application at boot

`BR2_PACKAGE_QOSP_AUTOSTART` (default on) installs `/etc/init.d/S99qosp`,
which supervises `/usr/bin/qosp-session` on tty1 — where the scanout puts its
frames. The serial console keeps its own getty, so there is always a shell to
debug from, and the application's own output goes to `/var/log/qosp.log`
rather than over the picture.

`qosp-session` selects the app and persistent paths: the app is `/usr/share/qosp/app.qa`, its
QLOG disk persists in `/var/lib/qosp`, and assets come from
`/usr/share/qosp/assets`. All three are overridable from the environment, so
the same script serves the appliance and a hand-run session.

The package creates `/var/lib/qosp` in the image and refuses symlinked state
ancestors during installation. Custom `QOSP_STATE` or `FPR_DISK` paths must
have already durable resolved ancestors on persistent mounted storage before
launch; runtime `mkdir -p` alone does not make new ancestor names durable.
`python3 tools/buildroot/package-install-check.py` checks the package install
macro against fresh, existing and volatile-link filesystem layouts.

### Readiness, restart and stop

The service requires an explicit application readiness signal. After its own
startup has succeeded, the application calls `Sys.ready Unit`; the host writes
its PID to the fresh `QOSP_READY_FILE` supplied by the supervisor. For a Files
application, call this after storage initialization. A live process alone is
not ready, and the marker does not assert continuing application progress or
hardware health. Existing applications that do not signal readiness can still
run by hand, but supervised startup will time out.

`S99qosp start` waits for the matching child PID's readiness before reporting
success. Parallel/duplicate starts share one instance. `status` distinguishes
running, starting, backoff, stopped and failed; a failed or stopped service
returns nonzero. A small `flock`/`exec` helper serializes lifecycle mutations;
Linux `/proc` start tokens protect stale PID records from signalling a reused
PID. The supervisor owns and reaps its application process.

An unexpected application exit (including status 0) restarts after exponential
backoff, with three restarts allowed for that supervisor's lifetime. Exhaustion
latches a failure and requires an administrative `start` or `restart`. A
requested stop never restarts the application. Stop sends SIGTERM so the host
can perform its durable shutdown, waits for a bounded grace period, then uses
SIGKILL if necessary. A nonzero shutdown result or escalation is reported as a
failure. A process still alive after escalation retains its ownership record
and prevents a second application from starting.

Ownership-record failures refuse launch or trigger bounded child teardown.
An incomplete launch marker is retained when the writer's identity or death
cannot be confirmed; later starts fail closed until an operator resolves it.
After supervisor death, stopping its orphan also reports an unconfirmed
shutdown because the exit status cannot be reaped. Once the child is gone,
an explicit administrative restart can safely create a fresh instance.
A supervised stop requires the recorded `stopped` result; a failed final-state
write also reports an unconfirmed shutdown.

The settings are environment variables, in decimal integer seconds/counts:

The service also sources optional `/etc/default/qosp` settings (override the
file with `QOSP_CONFIG`). Use `export` for values the application needs.
STAR64's overlay selects the optional PowerVR or LLVMpipe runtime, with
system Mesa as recovery, and supplies full-display defaults there; see the
[STAR64 hardware rendering record](../../docs/2026-10-14-STAR64-POWERVR.md).

| Variable | Default | Meaning |
| --- | --- | --- |
| `QOSP_READY_TIMEOUT_SEC` | 20 | Application readiness deadline per launch |
| `QOSP_STOP_TIMEOUT_SEC` | 15 | SIGTERM grace period; keep above the host's `QOSP_SHUTDOWN_MS` deadline |
| `QOSP_KILL_TIMEOUT_SEC` | 2 | Additional wait after SIGKILL |
| `QOSP_RESTART_MAX` | 3 | Restarts before failure is latched |
| `QOSP_RESTART_DELAY_SEC` | 1 | First restart delay |
| `QOSP_RESTART_DELAY_MAX_SEC` | 30 | Maximum exponential backoff |
| `QOSP_RUN_DIR` | `/var/run/qosp` | Instance ownership, readiness and state files |
| `QOSP_LOG` | `/var/log/qosp.log` | Service and application log |

Run `python3 tools/buildroot/service-check.py` from the QOS checkout to exercise
the actual scripts with real sessions and signals: concurrent start, readiness
refusal, finite restart/backoff, graceful/failed/forced stop, stale PID safety,
supervisor death and stop during startup. These host tests do not replace a
rebuilt image boot or Pi hardware tests. The image check remains a QEMU graphics
smoke test; it does not establish storage durability or long-running health.

For the complete host composition, first build `qosp` and an archive from
`tests/portableshutdown.fpr`, then run
`python3 tools/buildroot/service-check.py --real-only --host /path/to/qosp --archive /path/to/shutdown.qa`.
This passes the actual host and application through `qosp-session` and the
supervisor with one and two harts, then checks a clean durable stop and replay
after a fresh process starts against the same disk.

### Quiet Pi boot splash

The Pi 4 defconfig enables `BR2_PACKAGE_QOSP_BOOT_SPLASH`: a small early fbdev
helper displays the [QOS vector wordmark](../../assets/qos-boot-logo.svg), then
QOS carries it into its initial KMS buffer until the GUI draws. HDMI console
text, the cursor, kernel logos and firmware rainbow are suppressed. UART and
SSH remain available; Ctrl+Alt+F2 offers a recovery login. Other boards keep
their existing boot behavior. Connect and power the display before booting.
See the [implementation and validation record](../../docs/2026-10-14-PI-BOOT-SPLASH.md)
for build refresh requirements, logs, recovery and hardware test boundaries.
Run `python3 tools/buildroot/splash-check.py` to validate the logo and boot policy.

### Filling the screen

Whether the picture fills the display is the **application's** choice, not the
image's. `glInit 0 0` means "the display's own mode": the scanout is probed
first, the FBO is created at exactly that resolution, and the frame is blitted
1:1 over the whole screen — the log says `frame fullscreen`. Any explicit size
is kept and blitted centred in the mode, and the log says `frame centered`.

So an application meant to be an appliance should ask for `0 0`. The demos in
`programs/` ask for fixed sizes, because they were written for a window.
