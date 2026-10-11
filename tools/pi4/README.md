# Physical Pi 4 checks

These test QOS Portable on the running Buildroot/Linux Pi, and AArch64
FP-RISC Base executables. They do not boot QOS Native on ARM.

Build inside the existing ARM64 Linux VM, using the Pi image's Buildroot
toolchain rather than the VM's newer glibc:

```sh
tools/arm64-vm/vm.sh sync
tools/arm64-vm/vm.sh ssh 'bash ~/qos/tools/pi4/build.sh'
```

`TARGET_CC` and `FPRISC_ROOT` override the SDK and compiler paths. The output
defaults to `.qos/pi4/validation/bundle` in the Linux checkout. Copy its regular
files to a local bundle directory; retain `manifest.json` with the results.
The host includes storage fault-injection hooks for the refusal tests. It is
a test executable, not the production package.

From the Mac, with an already provisioned public-key login:

```sh
python3 tools/pi4/check.py \
  --host 192.168.0.232 --identity ~/.ssh/id_ed25519 \
  --known-hosts .qos/pi4/known_hosts \
  --bundle .qos/pi4/validation/bundle \
  --output .qos/pi4/validation/run --soak-seconds 300 --performance
```

The optional performance setting temporarily selects the CPU governor and
restores it on normal exit. The runner records actual frequency samples, CPU
time, peak resident memory and temperature. Benchmarks run three times each.
The script checks exact outputs or explicit invariants and expected refusal
statuses. The 20 ms process sampling limits precision for very short cases.

Each case gets separate state. Files replay, plugin replay and graceful-stop
tests use separate SD-backed files under `/var/lib/qosp/check-TIMESTAMP`;
other disks and Main disk copies use `/tmp`. Test state remains for inspection
and can be removed after collecting results. The installed Main disk is never
overwritten. Ensure enough space for about 80 MiB of persistent test disks.

Network cases require the three network archives from `build.sh`. Use
`--network-only` to repeat just those checks. Portable binds its listener to
loopback, so the driver forwards four simultaneous binary clients over SSH.
It waits for the server's explicit readiness before connecting. Use
`--host-key-alias` when checking another interface of the same enrolled Pi.
Run network suites serially because they use fixed test ports.

`service-check.sh` runs on the Pi with a unique `/tmp/qosp-service-check-*`
directory, a `portableshutdown.qa` path, and a test host path. It uses the
installed supervisor with isolated ownership, disk and log paths, deliberately
kills only that test host, verifies finite restart policy and administrative
reset, then performs a graceful stop.

Keep raw JSON/logs and pre-fix failures. A short successful soak does not
establish long-term memory stability or physical power-loss durability.
