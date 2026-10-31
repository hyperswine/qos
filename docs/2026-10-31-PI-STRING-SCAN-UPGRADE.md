# Pi 4 string-scan compiler upgrade

Date: 2026-10-31. Status: deployed and accepted on the physical Pi 4B.

QOS Portable was rebuilt from `4525c8d4ed689439c734746c10f36fcb31e017ee` with its compiler pin
and dependency lock updated to FP-RISC `1a09f0141c7bdb7ed022d7fcc1876f70666f661d`.
The compiler uses codegen revision 141; Portable ABI remains 22. Source export,
lock overlay and artifact hashes are recorded in the evidence. The build enables
`FPR_TYPED_IR_EARLY_LOOPS=1` and `FPR_TYPED_IR_STRING_SCAN=1`, with
`FPR_TYPED_IR_LOOP_MOTION=0`. It includes the production ES host, Main,
Clock, Logs, Browser, Disk, Terminal, Editor, a fresh seed disk and matching
native Editor compiler SDK. The installed writable disk was migrated separately.

The native AArch64 build uses Ubuntu 24.04, GHC 9.4.7, Cabal 3.8.1 and GCC 13.3.
The older builder needed libcurl development headers and Cabal dependencies
compatible with unix 2.8.8. Those changes affected only the disposable builder;
no FP-RISC source changes were required. The exact committed source export was
used throughout, independently of later local edits in the sibling checkout.

## Acceptance

- All 311 dependency pins resolve. Local disk updater, deployment helper and
  health helper suites pass (20, 9 and 7 tests respectively).
- The matching Editor SDK self-test passes in the builder and on the Pi,
  including source checking, QAR2 linking, immutable publication/update and
  invalid-source refusal. SDK lifecycle and publication checks also pass.
- 36 physical runtime cases pass with one/four workers, covering inbox ownership,
  nested regions, floating-point operations and parked-receive retention.
- 40 physical string-scan cases pass: optimization off/on, one/four workers,
  with identical output, exit status and traps. Cases include negative and
  oversized indices, empty strings, non-string input, accumulator/index overflow,
  near-maximum integers and zero-iteration paths.
- Isolated Main passes two navigation cycles through Files, Logs, Browser,
  Clock, Disk, Terminal and Editor with V3D graphics. Normal quit and SIGTERM
  both exit zero, with no timeout or forced termination. The original installed
  session stays unchanged during preflight.
- Deployment verifies immutable hashes, both disk superblocks and preservation
  of non-onboard user history and latest values. Configuration and boot-related
  hashes remain unchanged. The new Main starts and passes a deliberate supervised
  restart; the installed compiler responds correctly.
- The final 60-second service observation passes with zero automatic restarts.
  Main is `running pid=10621 restarts=0`; compiler is `running pid=9547 restarts=0`.
  Startup logs confirm V3D and 1024x600 scanout; KMS readback also yields a
  1024x600 PPM. The owner confirms the desktop is visible; manual interaction
  acceptance was not recorded.

After successful installation, SSH and ICMP briefly stopped responding while
the local gateway remained reachable. A later fresh SSH connection succeeded
without device mutation or reboot. Independent final checks verified installed
hashes, configuration, the rollback archive, and the same Main/compiler PIDs
with zero automatic restarts. Display readback passed. The interruption cause
is unknown; final verification is now complete.

Installed Main used 6.82% of one CPU core at 600 MHz over the 60-second check,
with RSS 45,504–46,068 KiB. The earlier session measured 7.00% and 47,888 KiB.
These values do not establish a compiler speedup.

The before/after health observations and preflight RSS samples are recorded in
[the machine-readable evidence](evidence/2026-10-31-pi-string-scan-upgrade.json).
These are short observations of different runtime ages and UI state, not a
paired Pi performance benchmark. No sustained soak, physical power-loss test
or hosted CI run is included.

## Rollback

A fresh stopped snapshot, checked archive and file hashes, configuration hashes,
source manifest, disk migration and service evidence remain on the Pi at:

```
/var/lib/qosp/deployment-pi-string-scan-20261031T092635Z/
```

To restore the pre-upgrade system, run as root on the Pi:

```sh
/var/lib/qosp/deployment-pi-string-scan-20261031T092635Z/rollback.sh
```

Rollback restores the old writable disk too, so writes made after this deployment
would be lost. The installer checked the complete sequential replacement budget
with an 8 MiB reserve and retained automatic recovery through startup and health
acceptance. Existing rollback archives were retained.

Private build and test artifacts are under
`.qos/validation/pi-string-scan-20261031/`. User disk contents and the rollback
archive remain on the Pi. The repository changes are the compiler pin,
dependency lock and this deployment evidence.
