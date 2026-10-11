# Power cuts on QEMU: the appliance image, cut and restarted

Date: 2026-10-10. Kind: a test harness and its first results. Runs
against the working tree described by `2026-10-10-PORTABLE-RELIABILITY.md`
(Qlog v3, `std/lifecycle`, the `S99qosp` supervisor, ABI v19) on the
Buildroot QEMU target, aarch64, built in the arm64 VM.

## What runs

`tests/powercut.fpr` is the appliance's one application for this test. On
every start it replays `pc/log`, reports `recovered records=K last=L` and
whether K == L (`contiguous`), publishes readiness with `Sys.ready`, then
appends one numbered record every 50 ms and reports each `committed N`.

`tools/buildroot/powercut-check.py` boots the image on a WORKING COPY of
the root filesystem, so `/var/lib/qosp/qosp.disk` persists across cycles
as an SD card would, follows `/var/log/qosp.log` over the serial console,
and each cycle:

1. asserts the recovery line: `contiguous`, and `last` at least the last
   record the previous cycle saw committed;
2. lets it commit for a random 0.5 to 4 s and notes the last commit seen;
3. cuts: `kill -9` of QEMU on odd cycles (the machine), `kill -9` of qosp
   inside the guest on even cycles (the process), where the supervisor's
   restart must bring it back and the same assertion holds again.

`--cache directsync` makes QEMU honor every flush. `--cache unsafe` makes
it ignore them, the nearest model of a card that acknowledges writes it
has not stored. Two loops may run at once (no host port forward).

    tools/buildroot/powercut-check.py --cycles 30 --cache directsync
    tools/buildroot/powercut-check.py --cycles 20 --cache unsafe

Building the image for it, in the VM (`tools/arm64-vm/vm.sh up`, `sync`):

    make -C ~/qos qos-app PROG=tests/powercut.fpr
    ~/qos/tools/buildroot/br.sh qemu qosp-rebuild && ~/qos/tools/buildroot/br.sh qemu

then on the Mac `tools/buildroot/boot.sh pull`.

## Results, 2026-10-10

| Run | Cycles before the disk filled | Machine cuts | In-guest kills | Lost records | Logs with a gap |
| --- | --- | --- | --- | --- | --- |
| `cache=directsync` | 10 (895 records) | 5 | 5 | 0 | 0 |
| `cache=unsafe` | 10 (875 records) | 5 | 5 | 0 | 0 |

Every cycle recovered at least every record it had seen acknowledged, and
every recovered log was contiguous. Every in-guest kill was followed by the
supervisor restarting the application within its readiness deadline and
the restarted process recovering the same log.

Both runs ended the same way: the default 8 MiB `qosp.disk` filled.

## Findings

- **The default disk fills in about twelve minutes of appends.** 8 MiB is
  2,048 pages; v3 keeps two for its superblocks and an eighth for SWAP;
  a record is a header page plus a payload page, so about 875 records.
  The refusal is honest (`Err "data partition full"`, before any write)
  and the application keeps running, but nothing on the appliance
  compacts or retires records: an event log keeps every record live by
  definition, so compaction would reclaim nothing. An appliance needs a
  retention policy at the application level (tombstone and compact, or a
  bounded stream), and a disk sized for it (`FPR_DISK_MB`, set at first
  run). This is the register's U7 for Files, met with a refusal and no
  recovery path.
- **A non-cooperating application never runs.** The first boot hosted a
  stale `app.qa` that never called `Sys.ready`. The supervisor behaved as
  documented: "did not enter within 20 seconds", three restarts with
  backoff, then "restart budget exhausted; administrative restart
  required". For an appliance that means an application built without
  the readiness call is a bricked box until someone logs in on the serial
  console. Either every shipped application opts in, or the package build
  refuses an archive that does not.
- **`wfi took 0 ms (r=-1 errno=4)` floods the log** around a kill: the
  host's park returns EINTR for the signal and reports it as a timing
  anomaly, several lines per restart.
- **What a QEMU cut proves, and what it does not.** QEMU writes through
  to the host file at once, and the host survives the kill, so even
  `cache=unsafe` loses nothing the guest handed to the virtual device.
  The runs prove Qlog v3's ordering against the guest's own file system
  and the supervisor's restart; a card's volatile cache is not modelled.
  The Pi run with a real power cut remains the test of that.

## Found on the way

The autodrop pass's new shapes (fprisc `5a340c3`) fired on the prelude's
`par2` and on `std/live`'s `serveProjected`, which return a CHILD of the
received root to their caller; both now `keep` it (fprisc `6412d70`).
