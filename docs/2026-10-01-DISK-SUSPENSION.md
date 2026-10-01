# Disk waits suspend actors

Implementation follow-up to disk suspension in the architecture/performance
backlog. Page layout and filesystem policy remain in FP-RISC.

## Native virtio

`hal/virt/blk.c` replaces the completion spin with 200-microsecond actor sleeps
until the used queue advances, retaining fences, status checks and interrupt
acknowledgement. The timeout is five seconds of the machine clock, rather than
a CPU-dependent loop count; boot contexts without a usable clock retain a
bounded fallback. This is timer-polled suspension, not a new interrupt-bound
queue or support for multiple outstanding DMA requests.

One lock covers the entire operation: write-buffer fill through completion,
and read completion through copying out. That is necessary once waiting yields
the hart: another actor must not overwrite the shared descriptors or buffer.
A killed owner marks the operation orphaned through its cleanup hook. A later
caller may reuse the DMA buffer only after the used queue confirms completion.

`tests/disknative.fpr` exercises concurrent writers/readers using separate pages
and checks every read over 30 rounds each. The actual driver passed under
RV64/QEMU with two harts: `native disk: True True`.

## Portable

A persistent host worker performs page `pread`/`pwrite`. Each request owns a
copied 4 KiB buffer and two references, one for the caller and one for the
queue/worker. Completion publishes the result with release/acquire. The app
parks between completion checks, then copies a read result and releases its
reference. Failure to submit or a failed I/O remains a failure.

The actor reaper releases a killed caller's reference; the worker can finish
without touching the actor's stack or arena. That required a routed runtime
sleep/cleanup hook and exposed an existing gap: killed sleepers were unlinked
but not reaped. They are now reaped once off their running stack, and their
blocked counter is retired. `tests/base/cleanup.fpr` checks the real reaper on
one and two harts. Cleanup callbacks must reside in the host/kernel for the
entire request lifetime, as the two disk implementations do.

The HAL additions are appended and QOS ABI is now v15. Rebuild the host,
kernel and process images together. The scheduler table additions likewise
require matching runtime builds. `fprisc.lock.json` pins the complete tested
compiler/runtime batch, `d3d5230bf1999f9b542031ca09aad55700cd897c`.

`tools/disk-suspend-check.py` compiles a separate test host with a 200 ms disk
latency injection. On one hart, the legacy synchronous path prints
`diskprogress: False bytes=4096`; the worker path prints `True`. The same gate
uses the actual worker under AddressSanitizer to check abandoning an in-flight
request, modifying the original write buffer after submission, successful
completion, out-of-range refusal and oversize refusal. Test-only compile flags
are absent from ordinary builds. The gate runs unconditionally in check-all.

Initial capacity discovery/open/stat/creation is still synchronous; this change
moves page transfers off the harts. Completion detection is a timed poll and
may add up to a timer interval of latency. A host syscall that never returns
can still hold the sole worker; a killed request is not a rollback of an
already-submitted write. No throughput improvement is claimed without a disk
latency/throughput benchmark on the target storage device.

## Verification

The native driver built and passed the concurrent RV64/QEMU regression. The
Portable legacy-versus-worker progress gate and ASan worker checks passed.
FP-RISC's complete base and standard suites passed, including the killed
sleeper cleanup regression. QOS's complete sweep exited 0 with
`ALL LEGS GREEN`; the updated disk gate also passed separately with its
native QEMU leg. The compiler-publication regression and exact cost-ledger
checks passed after repairing an in-place executable overwrite in the Makefile.
Unavailable websocket, graphics/GPU and alternate AArch64 legs remain skipped;
the legacy Sol example tally remains 38/47.
