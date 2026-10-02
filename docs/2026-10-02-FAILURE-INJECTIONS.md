# Audit failure injections

Date: 2026-10-02. Kind: verification record. QOS working changes based on
`aa94ea4`, FP-RISC pinned at `bca7278d60b22de7fab78b2f9111cc8a712c91b6`.
Closes the four unexercised paths at the end of
[AUDIT-FIXES](2026-10-02-AUDIT-FIXES.md).

Run `python3 tools/failure-injections-check.py`. Use `--output DIRECTORY` to
keep test kernels, archives, disk and per-boot logs; `--only netstall`,
`--only netorphan` or `--only nativerefusal` selects native probes. The console
probe always runs. `check-all.sh` includes this runner. Native prerequisites
are `riscv64-unknown-elf-gcc`, its `nm`, and `qemu-system-riscv64`; missing compiler
or QEMU is an explicit native skip.

## Fault boundaries and acceptance

| Fault | Injection | Acceptance |
|---|---|---|
| Native TX never completes | `QOS_NET_TEST` withholds one TX doorbell after submitting the descriptor; real `tx_take` / `nic_tx` / `tx_release` code runs with a 0.3 s test deadline | A child fail-stops at the deadline, its waiter gets `Err dead actor`, a 10 ms heartbeat runs at least ten times while waiting on one hart, and a later sender is refused within 100 ms. A normal TX completes before injection. |
| Sender killed mid-frame | Kill only after the driver confirms a withheld descriptor; start another sender before releasing the doorbell | The next sender remains blocked while the old frame is outstanding. Release notifies the real QEMU NIC; completion advances its used ring and the next send succeeds. Repeat without release: orphan times out, NIC goes offline, later send is refused promptly. |
| Full blocking console pipe | Fill a real pipe to `EAGAIN`, restore blocking mode, redirect stdout, call production `qos_console_putc` 5,000 times | Burst returns within 0.5 s, emits one stalled transition, drops/counts 5,000 bytes, preserves descriptor flags, writes the next byte after draining, and correctly repeats a one-byte stall/resume with its own drop count. A 5 s subprocess timeout catches unbounded blocking. |
| Native process storage send refused | Load a real relocatable process and fill its own sender channel in a static storage mailbox before releasing its entry barrier | The real `Sys.storeReq` -> `qos_store_call` ABI returns `Err storage: the storage actor refused the request`; kernel keeps running. Repeat with dead storage and storage killed after accepting a request: refusal and `Err dead actor` respectively. Healthy storage then answers `Ok`. Unrelated `Result` traffic remains queued in the process mailbox in every case. |
| Routed device fail-stop (additional check) | A second loaded process reads negative disk page -1 | Production `fpr_actor_fail` routes through the kernel scheduler table, only the process actor dies, the launcher gets `failed: dead actor`, and process images return to zero. Language `error` is deliberately a panic and is not this contract. |

Static mailbox capacity is **per sender**. Filling the kernel's channel does
not make a process's channel full. `QOS_PROCESS_TEST` exports a kernel-only
helper that uses `fpr_send_as` with the process root as sender to fill eight
entries and requires the ninth send to return `Err mailbox full`. The process
then makes its own ninth request through the unchanged syscall trampoline.

Both injection APIs are excluded from ordinary builds. The runner also compiles
production `net.c` and `process.c` objects and checks their symbols to establish
that the test entry points are absent. No test hook changes the refusal,
deadline, fail-stop or reclamation implementation.

## Fresh results

On macOS Apple M4, the host console probe and all twelve native boots passed:
three kernels, virtio v1/v2, one/two harts. The TX deadline observations were
approximately 0.30 s with 28 heartbeat messages in the initial matrix run.
All native acceptance fields were true, process reply strings matched exactly,
and no injected failure produced a machine panic. Final artifacts are under
`/tmp/qos-failure-final`; aggregate output is `/tmp/qos-injections-final.log`.

The earlier three-second sleeping full-mailbox fixture exposed why a permanent
non-consuming actor and the process's sender channel are necessary. That fixture
was replaced before accepting the test result.

## Limits

These are QEMU fault boundaries, not a physical broken NIC or measured target
latency. The test withholds notification; it does not simulate a device that
ignores a delivered notification, corrupts a used ring, or continues arbitrary
DMA after reset. It does exercise the production completion wait and orphan
ownership code on actual legacy and modern virtqueues. Network tests send raw
Ethernet frames through the shared TX path, not an end-to-end TCP session.

The console test has an independently drained stderr. It establishes the
full-stdout-pipe contract for one writer, not bounds for a blocked diagnostic
sink or arbitrary concurrent writers. The 0.3 s test deadline replaces the
production five-second deadline. The full repository sweep and physical hardware
were not rerun for this test increment.
