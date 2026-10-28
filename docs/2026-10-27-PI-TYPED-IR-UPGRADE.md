# Pi 4 typed-IR compiler upgrade

Date: 2026-10-27. Status: deployed and accepted on the physical Pi 4.
This updates QOS Portable on Buildroot/Linux, with Main, all six onboard apps,
the host and the native Editor SDK built together.

## Sources and build

The repository pin moves from `c5f7c2bf8dafeb0efbd1877c305d923a21848246`
to FP-RISC `7d8d2837f8fd007f739248eacf27ea0e54654b12`, codegen revision
135. The QOS application source is `d1a11db9626370bf7fbddf4780c6a7b595115382`
with that pin overlay. Source-export hashes are recorded in the evidence.
Portable ABI remains 22; every image carries the matching codegen stamp.

The build uses native AArch64 Ubuntu 24.04, GHC 9.4.7 and GCC 13.3.
FP-RISC `7d8d283` fixes an older-mtl build ambiguity: the A64 and X64 selector
imports hide the imported `fix` so their existing operand helper is unambiguous.
The same change builds with macOS GHC 9.8.2. No codegen revision bump is needed
for this import-only change.

The production bundle contains Clock, Logs, Browser, Disk, Terminal, Editor,
Main, a fresh 32 MiB seed disk, the Portable ES host and its matching Editor
compiler SDK. Diagnostic storage flags are omitted. The stopped writable disk
is migrated separately, with both fallback superblocks publishing the full
matching app set. Non-onboard history and latest user values are checked
independently; the updater validates seven old records and reclaims seven
superseded onboard records. The log head changes from 2527 to 1448, generation
15 to 17.

## Previous configuration and rollback

Before this update the Pi actually ran QOS `cd83f0a` and FP-RISC `2ce2f5a`,
codegen 49, rather than the newer pin in the Mac checkout. The board is a
Raspberry Pi 4 Model B Rev 1.4, Linux 6.6.28-v8, with V3D and 1024x600 KMS
scanout. Its CPU policy is `powersave`, observed at 600 MHz. Main uses
`/var/lib/qosp/Main.disk`; its native compiler uses `/tmp/fprd.sock`.

The fresh, verified rollback is retained on the Pi at:

```
/var/lib/qosp/deployment-pi-typed-20261027T115134Z/
```

`original.tar.gz` contains the previous host, Main, seed disk, stopped writable
disk, compiler SDK, file modes and service/configuration files. `original.json`,
`original.sha256` and the archive checksum describe it. `before/` also retains
the original settings, source manifests and baseline health samples;
`config-before.sha256` records the checked configuration and boot-related files.
The existing boot, kernel, firmware, network, GPU, input and service settings
are retained. Configuration hashes verify unchanged after installation.

To restore this stopped snapshot, run as root on the Pi:

```sh
/var/lib/qosp/deployment-pi-typed-20261027T115134Z/rollback.sh
```

This restores the pre-upgrade writable disk too, so later writes would be lost.
The installer has an automatic rollback trap for replacement, readiness or
short health-check failures. Space is budgeted for every sequential replacement
plus an 8 MiB reserve, and the compressed backup is checked before replacement.

## Acceptance

- Local QOS smoke: 16/16 on `e6fadfb`, immediately before the two-import
  compatibility fix. The final compiler builds on Linux and macOS.
- Final-pin physical Base probes: 36 successful runs across one/four workers,
  covering inbox quotas/sharing/ownership, nested regions and bounded loop
  storage, IEEE F64 operations, twelve live FP values across forced yields and
  stack growth, and parked-receive retention with inlining enabled/disabled.
- Matching native Editor SDK: real daemon, source checking, QAR2 assembly/link,
  immutable publication/update and invalid-source refusal pass in the builder
  and on the Pi.
- Isolated Main: two full navigation cycles through Files, Logs, Browser,
  Clock, Disk, Terminal and Editor with the matching candidate compiler.
  Normal quit and SIGTERM shutdown both exit zero without timeout, forced
  termination, fatal diagnostics or forced app-worker stop. The installed
  session stays unchanged throughout preflight.
- Installation: immutable hashes, user-history preservation, original
  configuration, readiness, a clean supervised Main restart, native compiler
  round trip and a 60-second installed-service observation all pass.
- Installed graphics: V3D and `/dev/dri/card1` 1024x600 fullscreen scanout are
  confirmed in startup logs. Read-only KMS capture produces a 1024x600 PPM;
  its checksum is in the evidence. This is not human visual acceptance.

The first graphical run timed out in its bulk proc/GPU diagnostic command;
its candidate subsequently shuts down cleanly. The accepted repeat uses
kernel `smaps_rollup` totals and skips optional GPU debug counters, retaining
all app, residency and shutdown assertions. Both attempts are retained.
SSH stalls also occurred before installation. The accepted deployment uses
`IPQoS=none` and connection reuse; device network settings are unchanged. A
later small check with `IPQoS=0` and `KexAlgorithms=curve25519-sha256` confirms
the same Main/compiler PIDs and zero restarts. Bulk diagnostic/image transfers
remain unreliable, so the on-device KMS capture is checksum-verified but has
no visual sign-off.

The preflight RSS samples are 45,080 and 45,552 KiB. Installed Main observes
43,544–43,996 KiB RSS, about 6.90% of one CPU core at 600 MHz, and zero automatic
restarts in both Main and the compiler. The prior session measured 78,876 KiB
RSS and 6.85% CPU. These are short observations with different runtime ages
and UI state, not a paired performance or long-term retention benchmark.
No overnight soak, physical power-loss test or GitHub CI run is included.

The [machine-readable evidence](evidence/2026-10-27-pi-typed-ir-upgrade.json)
contains exact source/artifact hashes, workload exits, disk migration,
configuration checks, service identities, health and rollback metadata.
Private build and test logs are under `.qos/validation/pi-typed-20261027/`;
user disk payloads and the rollback archive remain on the Pi.
