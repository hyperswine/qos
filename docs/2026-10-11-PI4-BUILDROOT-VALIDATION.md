# Pi 4 Buildroot validation, 2026-10-11

Tested a Raspberry Pi 4 Model B Rev 1.4, booting the customized Buildroot
image from SD with its original power supply and no monitor attached.
The QOS working tree was based on `0ceb7d1`, with the fixes below;
FP-RISC was `1e4a6e4`. Linux reported `6.6.28-v8`, Mesa `24.0.9`, and
the supplicant build was `2.12`.

## Hardware results

- Ethernet DHCP and SSH public-key login passed.
- Broadcom Wi-Fi reached WPA2 `COMPLETED`, obtained a DHCP lease, and
  accepted SSH after disabling firmware supplicant offload.
- Bounded Wi-Fi restart passed after waiting for old daemon cleanup.
- Main loaded the four onboard archives and reached readiness with four
  worker harts after pinning the graphics owner to hart 0.
- V3D 4.2.14 initialized surfaceless EGL 1.4 and OpenGL ES 3.1.
  Real GPU framebuffer readback produced a checked 960x600 Main screenshot
  and an onboard browser screenshot. Simulated evdev input exercised page
  switching, snapshots and browser launch.
- QOS graceful stop and start passed on the device.
- Remote Linux reboot changed the boot ID. SSH over Wi-Fi returned, Wi-Fi
  authenticated automatically, and Main again reached readiness with GLES.

Subsequent runtime tests exposed an additional failure: with no monitor,
offscreen frames never submitted their GL command stream, and Mesa V3D
eventually crashed after buffer allocation failed. An offscreen `glFlush`
frame boundary fixes the reproduced fault. The patched host passed 5,000
rendered frames and five-minute Main runs with one and four workers. It is
installed on the running Pi and included in the refreshed private SD image.
See [the runtime test report](2026-10-11-PI4-RUNTIME-TESTS.md) for the broader
suite, measurements, supervision and network results.

The initial image had two runtime failures that packaging checks and a QEMU
boot did not establish: the unpinned graphics actor stranded its EGL context
on another worker, and the firmware-managed Wi-Fi handshake timed out.
The source fixes are in both graphics composition roots and the Buildroot
overlay. The updated image packages the same Main archive tested on the Pi;
the running SD card received the fixes over SSH rather than a second flash.
Private manifests, images, boot IDs and captured frames stay under `.qos/pi4`.

The ARM64 Linux host regression `tools/guishell-check.py` also passed with
four workers: two UI boots, real desktop GL readback, onboard clock/browser,
launch refusals, pointer routing and graceful shutdown. Its Xvfb wrapper now
wraps the harness so readiness is checked against the actual application PID.
Provisioning checks, package-install checks and shell/Python syntax checks
passed. These host results are distinct from the physical Pi results above.

## Boundaries

No HDMI display, physical keyboard, audio output, physical power-loss test or
overnight soak was performed. The later network tests also passed with
Ethernet administratively down, with only the Wi-Fi route present; Ethernet
was then restored. This supersedes the original two-interface-only checks.
A readiness marker establishes successful startup, not ongoing health.
The Pi kernel still uses the broad
upstream `bcm2711` baseline rather than a fully pruned driver configuration.
