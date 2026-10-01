# Disk failure and lifecycle hardening

Date: 2026-10-01. Kind: implementation record. Follows
[DISK-SUSPENSION](2026-10-01-DISK-SUSPENSION.md), which named the gaps closed
here: a native caller could wait forever behind an orphaned transfer that
stalled, and the Portable worker queue had no explicit bound.

## The rule

Nothing in the disk path halts the machine, and nothing waits without a
deadline. A page transfer that cannot complete **fail-stops the calling
actor** instead (`fpr_actor_fail`, new in FP-RISC's runtime). This covers a
missed deadline, a stalled device, a refusal, an I/O error, a missing disk
and an out-of-range page. The reason goes to the error ring and the actor
dies alone. An RPC caller waiting on it hears `Err "dead actor"`: the
storage actor's clients get `Err "storage service: dead actor"` through the
checked request/reply path. Argument-type errors (a programming mistake)
still panic.

The deadline is 5 s, the virt driver's, recorded in
[BOUNDS](2026-09-19-BOUNDS.md). Fail-stop was chosen over error values
threaded through `qlog`, because `qlog` ignores `blkWrite`'s result. A
sentinel return would have turned an honest stop into a silently lost write.
The storage actor stays down after a failure: nothing restarts it today.
Errors as values in `qlog`, with a storage actor that survives a device
failure, is the next step if that matters.

## Native (`hal/virt/blk.c`)

- **The owner's deadline.** A request the device has not completed within
  the deadline marks itself an *orphan* and fail-stops its owner. The
  owner's timeout used to panic the machine.
- **DMA buffers are preserved.** An orphan's header, data and status
  buffers stay reserved while the device may still use them. They are freed
  only when the used ring shows the request complete, or after a confirmed
  device reset.
- **Waiting behind an orphan has a deadline.** The next caller reclaims the
  orphan's buffers when the device completes it. Once the orphan is older
  than the deadline, that caller resets the device: it writes status 0 and
  waits until status reads back 0, after which the device may no longer DMA
  (virtio 1.x, 4.2.2.1). It then rebuilds the queue (`blk_init`, shared with
  boot) and proceeds. The stalled request is dropped and logged.
- **Offline.** If the device does not read back 0 or refuses to
  re-initialize, the buffers stay reserved for good, the disk is marked
  offline, and every later request is refused at once.
- A killed owner (the cleanup hook) becomes an orphan in the same way.
- A live owner has its own deadline. A caller that has waited three
  deadlines for the lock is refused, which only guards against a bug.

## Portable (`hal/unix/blk_raw.c`, `qos/appside/hal.c`)

- **The caller's deadline.** The app waits for its job at most the deadline.
  Past it, the app drops its reference and fail-stops. The worker still
  holds the job's buffer and frees it when the host call returns, so a
  write that was already submitted is not rolled back.
- **Overload refusal.** A submission is refused (`NULL`) while the worker is
  *stalled*: the job it is running, or the oldest one waiting, has been in
  the system longer than the deadline (`$QOS_BLK_DEADLINE_MS`, default
  5000). The queue therefore holds at most what arrives within one deadline,
  and stops growing behind a worker that is not draining. It accepts work
  again as soon as the worker catches up.

## Tests

- **`tools/disk-harden-check.py`** (a `check-all.sh` leg):
  - `tests/diskstall.fpr`, a native test kernel built with `-DQOS_BLK_TEST`
    and a 0.3 s deadline. The test switches withhold a request's doorbell
    and make a reset fail. It checks that a stalled owner fail-stops and
    that a reader behind it resets the device and reads the page as it was:
    the stalled write never landed. A new write lands. An owner killed
    mid-request does not land, and the next write recovers. A failed reset
    takes the disk offline, and the next request is refused in under 0.2 s.
  - `tests/diskstallp.fpr`, through a real `-DQOS_BLK_TEST` `qosp` with a
    slow first two reads. The storage actor fail-stops and its client gets
    `Err storage service: dead actor`. A late caller fail-stops. A request
    while the worker is stuck is refused. After the worker drains, a write
    and a read land.
- **`tests/host/disk_async_check.c`** (in `disk-suspend-check.py`, under
  ASan): the real worker with a blocked `pread`. Within the deadline, work
  queues. Past it, new work is refused. Once the worker drains, work is
  accepted again.
- **FP-RISC `tests/base/actorfail.fpr`** (`check_base.py`) checks
  `fpr_actor_fail` on one and two harts.

## Not done

- The native driver is still one outstanding request with a timed poll.
- A Portable host syscall that never returns still holds the sole worker,
  but it is now visible as refusals instead of an unbounded queue.
- A fail-stopped storage actor is not restarted.
