# Pi 4 compact-runtime compiler upgrade

Date: 2026-11-04. Status: deployed and verified on the physical Pi 4B.

The production Portable ES host, Main, Clock, Logs, Browser, Disk, Terminal,
Editor, seed disk and matching native Editor SDK were rebuilt from QOS
`6a273c6dd9f6fddebc4cefaf1ad36c0ba82086dd` with FP-RISC
`22e1e5537370f48ed1c7bd8f3435aa4a0b74836c` (codegen 162).
Portable ABI remains 22. The matching runtime incorporates the compact-cell,
raw-buffer and module-layout changes described in
[the compact runtime record](2026-11-04-COMPACT-RUNTIME.md).

The build used isolated committed-source exports. Only the exported compiler
pin was updated; the checkout's frozen release pin was preserved. All 311
dependency pins resolved without regenerating `fpr.lock`. The ARM64 builder
used GHC 9.4.7 and omitted the GHC 9.8.2 release freeze in its export, following
the compiler's Linux CI policy. Early loops and string-scan proofs were enabled;
loop motion remained disabled. Source archives, overlays, builder identity,
SDK identity and installed hashes are in
[the machine-readable evidence](evidence/2026-11-04-pi-compact-runtime-upgrade.json).

## Acceptance

- Local disk updater, deployment helper and health helper suites passed
  (20, 9 and 7 tests). SDK lifecycle, publication and signal checks passed.
- The matching SDK self-test passed both in the builder and on the Pi:
  native AArch64 QAR2 compilation, immutable publication/update and rejection
  of invalid source.
- 44 physical runtime cases passed on one/four workers: inbox ownership,
  nested regions, floating-point state, parked receives, compact/legacy
  allocation extents, mixed raw/managed reuse and allocation-overflow refusal.
- 40 physical string-scan cases passed with optimization off/on and one/four
  workers, preserving output, exit status and bounds/overflow traps.
- Isolated Main passed three navigation cycles through Files, Logs, Browser,
  Clock, Disk, Terminal and Editor with V3D rendering. Normal quit and SIGTERM
  both exited zero without timeout or forced termination. The installed
  session remained unchanged throughout preflight.
- The stopped writable disk migration preserved 46 non-onboard records,
  including their history bytes and latest values. Seven onboard app/index
  records were replaced. Both superblocks were validated. Existing rollback
  archives and service/boot-related configuration were preserved.
- Installed Main passed startup, a deliberate supervised restart and a
  60-second health check with zero automatic restarts. Final Main PID was
  17227; compiler PID was 16140. A fresh SSH connection independently verified
  live identities, installed hashes, SDK revisions and the rollback archive.
- HDMI KMS readback and image inspection confirmed the 1024x600 Main launcher
  on V3D. This is framebuffer evidence, not manual user interaction acceptance.

The SD filesystem initially had about 25 MiB free. Two inactive 32 MiB test
disk images were rewritten sparsely, preserving their bytes, checksums,
permissions and modification times. This recovered 56 MiB without deleting data or
rollback archives. The installer checked sequential replacement space with
an 8 MiB reserve; about 61 MiB remained free afterward.

The short installed observation measured 7.08% of one CPU core at 600 MHz,
with RSS 45,084–45,668 KiB. The older session had a different runtime age and
state; these measurements do not establish a performance gain. No sustained
soak, physical power cycle or bare-metal boot qualification was performed.

## Rollback and retained evidence

The verified stopped snapshot and rollback script are on the Pi:

```sh
/var/lib/qosp/deployment-pi-compact-19700104T184902Z/rollback.sh
```

The Pi's wall clock was unset, so its directory timestamp is not the actual
deployment date. The clock and network configuration were not changed.
Rollback also restores the old writable disk, discarding subsequent writes.

The backup directory contains installed hashes, disk preservation reports,
configuration hashes and final verification. Its `verification/` directory
retains runtime cases, SDK self-test results and raw health samples. Private
build artifacts and the HDMI capture are under
`.qos/validation/pi-compact-20261104/` locally. User disk contents and the
rollback archive remain on the Pi. The temporary build container is stopped.
