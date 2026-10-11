# Portable storage, shutdown and supervision

Kind: implementation contract and focused validation. Updated 2026-10-10.
Describes the accompanying changes on QOS base revision `2dfab4d`:
Portable Qlog v3 and host/app ABI v19.

The Portable appliance has three cooperating owners: Qlog interprets the
storage format, an FP-RISC lifecycle actor administers Files/block/network,
and a Linux service supervisor owns the host process. Host C implements the
flush and deadline mechanisms. Policy stays in FP-RISC and the service scripts.

## What an append acknowledgement means

Portable's block worker serializes read, write and flush jobs in one FIFO.
A flush calls `fsync` on the backing file (and `F_FULLFSYNC` on macOS when
supported), then `fsync` on its parent directory. Errors propagate; an
abandoned caller does not free a job while the host syscall still uses it.
The existing I/O deadline and stalled-worker admission checks also cover flush.
At most 64 physical jobs may be queued or running, including work whose
caller has abandoned it.

Qlog v3 reserves page 0 and the final physical page for checksummed,
generation-numbered superblocks. An append writes its new record pages,
flushes them, publishes the next superblock in the alternate slot, and
flushes again before replying `Ok`. A crash before publication leaves the
old head; a crash during publication can leave either complete generation.
The newest valid generation wins. A caller that lost its reply still has an
unknown outcome: restart does not replay the write automatically.

Legacy v1/v2 images migrate on a flush-capable device only when the final
page can be reserved without overwriting committed DATA. An interrupted
legacy compaction is refused. Invalid nonzero metadata is refused, never
silently treated as an empty disk. Formatting is allowed only for blank
media. SWAP is scratch space; migration reserves its final physical page.

Compaction first builds the live image in SWAP. It refuses before disk
mutation if that image does not fit. The staged image is flushed, then a
checksummed PREPARED descriptor is published and flushed in both metadata
slots before DATA is overwritten. Recovery validates the staged checksum
and replays the entire copy. Both stable descriptors must be flushed before
SWAP is reusable. Consequently the current 1/8 SWAP allocation limits how
large a live image can be compacted; it is a deliberate refusal boundary,
not a general full-disk collector.

Durable startup and compaction validate every committed record's header,
bounds, available payload checksum and bulk framing before accepting or rewriting it.
Append and compaction reject stale heads before mutation.
Keys must be nonempty tokens without ASCII whitespace, control bytes or DEL,
and the encoded record header must fit one page. Invalid append inputs are
refused before disk mutation; higher layers must encode other filenames.

These guarantees depend on the host filesystem and device honoring their
flush contract. Checksums detect accidental damage; they are not an
adversarial integrity scheme. Native virtio currently reports flush as
unsupported and retains the buffered v2 format. A v3 image requires a
flush-capable service.

The Buildroot package pre-creates the default `/var/lib/qosp` directory in
the image and refuses symlinked state ancestors during installation. Custom
`QOSP_STATE` or `FPR_DISK` paths require already durable resolved ancestors
on a persistent mounted filesystem before launch. Runtime `mkdir -p` alone
does not establish that guarantee.

The separate `Sys.storeReq` compatibility channel used by per-app KV
callers retains its length-framed `qos-store/<id>.kv` format. Successful
appends now follow checked writes, file flush and directory barriers, including
the `qos-store` directory's name in its parent. Replay and index calls exclude
EOF-truncated final records; the next append repairs only that trailing
fragment. Malformed framing refuses further writes. Failed writes, barriers
or closes return `Err "storage outcome unknown"` and must not be retried
automatically. Replay or index output exceeding the caller's capacity returns
an error rather than a partial success. This older format has no payload
checksum and cannot detect arbitrary payload damage. Its working-directory
ancestors must already be durable.

## Shutdown ownership and deadlines

`std/lifecycle.fpr` owns the administrative handles while the root actor can
be waiting for input or an application. `System.qa`, the Main Profile shell,
and the shared Portable services composition use this coordinator. Normal
Main Profile exit arms the host deadline and asks it to stop. SIGINT/SIGTERM
become a host flag, which it polls without running FP-RISC from a signal handler.

The shutdown sequence stops network admission, quiesces Files, drains
admitted block requests, and issues a final flush. Files stays quiesced even
if drain or flush fails. A successful Portable acknowledgement means that
barrier completed. Native's result explicitly says its durable flush is
unsupported. Failure is a nonzero host exit, not a clean shutdown claim.

An independent host thread enforces `QOSP_SHUTDOWN_MS` (default 5000 ms,
accepted range 1..600000). Repeated signals do not extend it. An app that
never cooperates, a blocked actor, or stalled cleanup causes exit status
124 at the deadline. Ordinary signal exits without an explicit shutdown
acknowledgement fail. The bound assumes the host OS schedules the watchdog;
it cannot force a kernel to reap a task stuck in uninterruptible I/O.

The host/app ABI is v19. Apps and plugins built for the previous ABI must be
rebuilt: the appended callbacks provide shutdown request, deadline arming,
completion and explicit readiness.

## Supervision and restart

Buildroot's `S99qosp` starts one supervisor, which owns and reaps one detached
application session. It uses process start identities, not PID alone, and a
serialized administrative lock to avoid duplicate starts and stale-PID
signals. A fresh ready file must contain the current child PID. The Main
Profile publishes it only after storage, namespace and graphics attachment;
this does not claim that the first frame has rendered. Arbitrary applications
opt in by calling `Sys.ready Unit` after their own required
services are ready. The bundled Main Profile plugins explicitly re-export
their appkit entry points at the archive root for scoped module lookup.

Unexpected exit or startup timeout consumes a finite restart budget, with
exponential backoff. Exhaustion leaves a failed state requiring an explicit
administrative restart. Stop requests graceful termination, waits a bounded
period, escalates to SIGKILL if necessary, and reports a failure for a
nonzero shutdown or escalation. Ownership is retained when a child cannot
be reaped, so a second writer is not started over it. Configuration and
numeric defaults are listed in `tools/buildroot/README.md`.

Readiness is a startup assertion, not an ongoing health heartbeat. This
supervisor restarts the whole Portable process; it does not transparently
restart individual application actors. Files retains its existing limited
on-demand Qlog replacement and never replays an interrupted request.

## Validation and remaining scope

Focused checks cover the real FIFO worker's flush ordering/error/lifetime
rules, fresh-process Qlog recovery snapshots, Portable graceful and forced
shutdown, and service readiness/retry/stop races. See
`tools/portable-durable-check.py`, `tools/portable-shutdown-check.py`,
`qos/tests-host/blkflush-check.sh`, `qos/tests-host/store-check.sh` and
`tools/portable-store-check.py`. `tools/buildroot/service-check.py` exercises
the appliance scripts; its `--real-only --host ... --archive ...` option
checks the actual session/host/application composition. The real GL Main
Profile shutdown and restart check is `tools/guishell-check.py`.
Existing Files and Native routing checks remain relevant regressions.

Host tests and constructed crash snapshots do not establish physical
power-loss behavior. The Linux Buildroot QEMU image has now been booted and
cut repeatedly; see [the power-cut harness and results](2026-10-10-POWERCUT-QEMU.md).
Those runs do not model loss from a physical device's volatile cache.
Raspberry Pi 4 storage power-cut tests and extended application soak tests
remain platform validation work. The existing Files mailbox byte/count limits, client waits
without deadlines, and wider actor supervision are separate work.

The current compiler's module safety trust also depends on source paths.
Normal checkout builds pass, while isolated store-only FS/Lifecycle imports
can report different safety-annotation diagnostics after removing working-path
trust. The module lock checks hash resolution; it does not prove an isolated
store-only closure. Aligning those compiler trust rules remains separate work.
