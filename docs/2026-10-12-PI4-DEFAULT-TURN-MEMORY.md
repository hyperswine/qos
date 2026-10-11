# Pi 4 default turn-memory validation

Date: 2026-10-12. Physical Raspberry Pi 4 Model B Rev 1.4, aarch64,
Buildroot Linux, connected over Wi-Fi. FP-RISC
`fd65bc9f2274647f10e95e98d7121e584055c796`; QOS `b265500`.
The kernel host, app and onboard plugins were rebuilt together using the
Pi Buildroot SDK. Bundle SHA-256:
`f5282b2bbe1640cff39ccf17d67607344cd6f8db062bb1053b2e4e5bfa455c3e`.

## Executed checks

All exited successfully, without timeout or forced kill:

| Check | Hardware result |
|---|---|
| `loopstate`, one/four workers, 64 MiB heap | One million turns; caller allocations below 4 KiB, retained heap below 4 MiB |
| `scopecancel`, one/four workers | Nested scratch arenas and transferred states reclaimed on cancellation |
| `mvuportmemory`, one/four workers | 20,000 FIFO batches; received roots released, bounded retained memory |
| `mvuscoped`, one/four workers | Ordinary `MVU.run`, 20,000 frames below 4 MiB retained |
| `arenamigrate`, four workers | Actual migration observed with nested scopes intact |
| `logmemory`, one/four workers | 2,000 cycles; zero ARC-root growth |
| `gfxmemory`, four workers | 100,000 frames below 2 MiB retained; backend state survives |
| `gfxheadless`, four workers | 5,000 real V3D GLES frames; image saved successfully |
| `filesshutdown`, four workers, isolated disk | Authorization, drain, permanent refusal, reopen/persistence and failed-drain latch pass |

The GLES backend reported EGL 1.4 (surfaceless), V3D 4.2.14 and OpenGL ES
3.1 Mesa 24.0.9. No display was attached.

## Main session

Two isolated Main runs used four workers, the matching onboard Browser,
an injected input FIFO, and the same separate SD-backed disk under
`/var/lib/qosp/check-memory-default-fd65bc9/`. Files and Logs opened,
scroll/navigation keys worked, both launcher pages worked, and Browser
opened and responded. Retrieved screenshots show the vertical Files and
Logs views on the actual Pi GLES backend.

| Run | Duration | Sampled RSS, first → last | Shutdown |
|---|---:|---:|---|
| 1 | 106.08 s | 43,324 → 43,324 KiB, 16 samples | Normal quit; storage drained and flushed |
| 2 | 100.10 s | 41,396 → 41,396 KiB, 13 samples | SIGTERM; host acknowledged shutdown |

Both readiness files were removed. Peak sampled temperature was 61.8°C;
the observed CPU frequency was 600 MHz. These are short regression runs,
not evidence of an overnight soak, sustained peak performance, HDMI output
or recovery from power loss. Growing application state remains unbounded.

The installed supervisor/session remained running throughout, with the
same child PID and zero restarts. Its app and stored disk were not replaced.
The separate SD test disk was removed after validation.
Detailed logs, runner JSON, memory samples, screenshots and the local test
driver are retained in the ignored directory
`.qos/pi4/validation/memory-default-20261012/`.

## Automatic receive-loop follow-on

After the library-default checks passed, FP-RISC
`f79d8e4a0717a2cf2263b50378ae71b52b07988a` added automatic regions for
recognized value-state recursive receive groups. QOS now pins that revision.
The Pi fixture uses ordinary recursion, without a loop/arena/reset API.

The final SDK-linked executable, built with a fresh assembly cache, has SHA-256
`8642b131cbbdf7ddcec54a3ad2b8f78b56d5c18df7e7a4b996972a95bce17f01`.
On the physical Pi, with a 64 MiB heap:

| Workers | Messages | Duration | Peak RSS | Result |
|---|---:|---:|---:|---|
| 1 | 1,000,000 | 8.32 s | 1,920 KiB | Caller/final state intact; bounded retained heap; stable ARC roots |
| 4 | 1,000,000 | 8.42 s | 2,048 KiB | Same assertions pass |

The complete Base suite, symbolic cost checks, Linux ARM64 recursive-loop
checks, and a four-hart RV64 QEMU run of 10,000 messages passed. QOS native
boot, Portable MVU, real one/four-worker plugin reloads and the Linux ARM64
real-GL Main harness passed with this implementation. That Main harness
also exercises onboard Clock/Browser, scrolling, launch refusals and two
shutdown paths. The installed Pi session still has not been replaced.

The compiler handles direct/mutual tail calls, case/let branches and receives
through imported helpers when state has closed value-type evidence. Infinite
actors need no concrete result type when the pass proves they cannot return.
Mutable/linear state, function-valued state, non-tail or escaping recursion,
missing type evidence and explicit region owners remain unchanged and are
reported with `FPR_RECEIVE_NOTES=1`. Growing live state and missed received-root
ownership still require application fixes. Runtime cost calibration now
reports both primitive-only and automatic-turn measurements; state copying
is additional work, rather than a free optimization.
