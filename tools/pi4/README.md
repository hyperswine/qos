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

For a longer observation of an already running shell:

```sh
python3 tools/pi4/soak.py \
  --host 192.168.0.232 --identity ~/.ssh/id_ed25519 \
  --known-hosts .qos/pi4/known_hosts --seconds 1800 --interval 30 \
  --output .qos/pi4/validation/soak
```

This does not restart or stop the application. It fails on a changed ready PID
or failed sample, and records full smaps, CPU counters, temperature and binary
hashes. Optional V3D BO totals require debugfs to be mounted; they are global
GPU counters, not per-process RSS. `--ready-file` and `--app` select an isolated
test instance. `complete.json` confirms observation completed, not application
correctness. Check its logs, GPU progress and shutdown separately.

The bundle also contains a 20,000-frame scoped MVU memory test and a
100,000-frame graphics-owner memory test. Both check buddy allocation rather
than confusing virtual reservations with resident or logically live memory.

The arena migration case parks inside nested `Sys.arena` and `Sys.loopWith`
calls and requires observed migration on four workers. Qlog has a separate
driver because it needs a checksummed binary seed and two boots of each disk:

```sh
python3 tools/qlog-memory-check.py \
  --host 192.168.0.232 --identity ~/.ssh/id_ed25519 \
  --known-hosts .qos/pi4/known_hosts \
  --archive .qos/pi4/validation/bundle/qlogmemory.qa \
  --runner .qos/pi4/validation/bundle/runner \
  --output .qos/pi4/validation/qlog-memory
```

This uses the installed `/usr/bin/qosp` and separate SD-backed disks. It checks
large binary reads, replay, tombstones, compaction, persistence and a 4 MiB
bound on Qlog's sampled logical pool allocation, on one/four workers with a
64 MiB application arena (`QOSP_ARENA_MB`) and a separate hosted heap cap.
It checks under 4 MiB global growth across the finite workload: successful
block I/O reuses its worker and relay. Cancellation/failure can still replace
workers, and growing live indexes remain separate admission work. The driver removes only its
own two disk copies after success and retains logs. Without `--host`, it builds
and tests the local Portable host.

For a matching candidate bundle already extracted on the Pi, exercise Main's
Files/Logs scroll views and onboard Browser repeatedly, with a separate
SD-backed disk and two shutdown paths:

```sh
python3 tools/pi4/main-soak.py \
  --host 192.168.0.233 --host-key-alias 192.168.0.232 \
  --identity ~/.ssh/id_ed25519 --known-hosts .qos/pi4/known_hosts \
  --remote-dir /tmp/qos-candidate --seconds 7200 --interval 30 \
  --output .qos/pi4/validation/main-candidate
```

The directory must contain matching `runner`, `qosp-es`, `main.qa` and a
32 MiB `Main.disk` seeded with the standard eight-shortcut Main profile.
This driver preserves the installed service and copies only the candidate's
seed disk. It checks UI log acknowledgements on every cycle, unchanged test
PID/service state, sampled RSS growth (default 16 MiB allowance), normal quit
with storage drain, and a second boot stopped by SIGTERM. Successful runs
remove only their own SD disk and retain logs; failures retain that disk for
inspection. `complete.json` confirms those assertions passed. A short run
still does not establish long-term stability or power-loss recovery.
The driver sets `QOSP_ARENA_MB` explicitly (default 256 MiB, adjustable with
`--arena-mib`). `FPR_HEAP_MB` limits the hosted Base runtime; it does not cap
the loaded QOS application's independently initialized buddy arena.

To attribute growth, build `tests/mainmemory.fpr` as the candidate `main.qa`
and add `--memory-probe`. This uses the same shell boot and shutdown paths,
with a test-only F12 update callback. Each sample records buddy arena/free
KiB, reserved KiB (their difference), ARC root count, and the model actor's
cumulative pool bump gauge. Reservations include stacks and reusable slabs;
they do not measure reachable objects. The bump gauge is not live bytes.
The driver also saves this process's DRM fdinfo when the kernel supplies it,
separately from global V3D BO totals. Missing DRM counters remain empty.
Use a fresh disk with matching onboard plugins after changing shared modules.

The bundle now includes `mvufailure` and `blockmemory.qa`. The first checks
service admission/death, worker death, port failure and Result cleanup; the
second checks 8,192 repeated reads after warm-up under a real 64 MiB arena.
The standard Pi driver runs both with one/four workers. For an isolated Qlog
candidate, `qlog-memory-check.py --host-bin /tmp/candidate/qosp-es` selects an
already uploaded matching host, and `--host-key-alias` uses the enrolled key
when the Pi is reached through another interface. Defaults retain the
installed host path. Neither option installs an executable.

## Updating an installed Main disk

Rebuild `programs/main.fpr`, all four `apps/{clock,logs,browser,disk}.fpr`
archives and the Portable ES host from matching QOS/FP-RISC revisions. Use
the normal entry and omit diagnostic `QOS_BLK_TEST`/`QOS_STORE_TEST` flags.
Changing a shared wire type requires replacing the shell and every onboard
archive together. Replacing `/usr/share/qosp/Main.disk` alone does not update
the existing writable `/var/lib/qosp/Main.disk`.

First exercise the candidate on an isolated copy of the writable disk. Then
stop `/etc/init.d/S99qosp` cleanly and take a fresh disk snapshot. On the build
machine, prepare a separate replacement:

```sh
python3 tools/pi4/update-main-disk-check.py
python3 tools/pi4/update-main-disk.py stopped.disk updated.disk production/
```

`production/` contains the matching four `.qa` files. The tool requires two
valid stable v3 superblocks, verifies the complete committed record stream,
and appends four new archive records. It preserves the original committed
record bytes, app index and user history; both fallback superblocks publish
the matching bundle. It refuses legacy/pending/corrupt disks, insufficient
space, generation exhaustion and a custom index. Recover or compact through
QOS first; rebuild additional indexed apps before adapting an upgrade for a
custom profile. The source and any pre-existing output are never overwritten.

Keep rollback copies of `/usr/bin/qosp`, `/usr/share/qosp/app.qa`, the seed
disk, and the stopped writable disk. Install the new host, shell, seed and
updated writable disk while stopped, flush them, and start the supervisor.
Verify installed hashes, ready PID, restart count, real KMS/EGL ownership and
logs, then exercise a clean supervised restart. Keep the stopped original
disk for rollback; restoring it later would discard writes made since the
upgrade. Never install a diagnostic Main bundle as the production session.
