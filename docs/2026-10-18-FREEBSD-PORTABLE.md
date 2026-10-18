# FreeBSD Portable compatibility check

Kind: fresh QEMU validation record, 2026-10-18.
QOS snapshot: `cc0334ad6eb45c7e32ac7c6eb9f9851705a273eb`.
FP-RISC: the QOS lock revision `905c4f42b143a14976e2170cd9d38f2f487ac16e`,
with the two explicit networking includes described below. Portable ABI v22.

The headless Portable host still runs on FreeBSD. The unmodified pinned
runtime first failed to compile; a two-line header fix was needed. This
record does not validate EGL/DRM, the graphical Main shell, physical input,
or native compilation of the Haskell compiler inside FreeBSD.

## Guest and build

Used the repository's `tools/freebsd-vm/vm.sh` and the official FreeBSD
14.5-RELEASE ARM64 BASIC-CLOUDINIT UFS image. Its compressed SHA-256 was
`8c0309f7aaa69674c3e657eb4d4642d5eef816094aea3c7c0b0b505a7049f0ca`,
checked against the release server's `CHECKSUM.SHA256`. The image performed
its normal first-boot update; tests ran on FreeBSD 14.5-RELEASE-p2.
QEMU used macOS HVF, four ARM64 vCPUs, 4 GiB RAM and the image's 1 GiB swap.
No packages were installed for the tests. The image's package list remained
`firstboot-freebsd-update` and `pkg`.

Built the exact pinned FP-RISC compiler in the isolated sibling worktree
`fprisc-freebsd-check`. Generated assembly with `fpr compile --system=posix
--target=a64`, then copied that assembly, its emitted units, the pinned
runtime/machine sources and the QOS host HAL into the guest. FreeBSD's base
Clang 21.1.8 compiled and linked the native FreeBSD executables. The Portable
archives were built with the normal `make qos-app APP_HOST=a64` rules.

Both `qosp` and the separate native `liveboard` server were verified as
FreeBSD ARM64 ELF executables using `/libexec/ld-elf.so.1`; their dynamic
dependencies were only base `libthr.so.3`, `libm.so.5` and `libc.so.7`.
This tested code generation plus a native FreeBSD C build, not the older
Linux-to-FreeBSD sysroot cross-build recipe in the VM README.

## Build regression and harness corrections

FP-RISC's newer `machine/posix/os_connection.c` and `os_resolver.c` omitted
`<netinet/in.h>`. FreeBSD reported undeclared `IPPROTO_TCP` and incomplete
`sockaddr_in`/`sockaddr_in6` types. Adding that header to each file fixed
the native build. These additions are present in both the isolated test
worktree and the main FP-RISC checkout. No compiler pin was changed and no
changes were committed or pushed by this check; a clean checkout of the
recorded lock revision still needs those two includes.

The existing FreeBSD server harness also assumed obsolete JavaScript source
spellings (`window.__LV__`, `new WebSocket`, `.col`) and required the transient
"working" frame before job completion. The typed JS emitter can use bracket
access and parenthesized constructors; coalescing writers can skip the
intermediate frame. Its checks now require the page contract and completed
job. Failed session opens report the session number and SSH diagnostics,
and every opened connection is registered for cleanup immediately.

The scratch Portable HTTP harness was corrected to detach its FreeBSD daemon
with `-f`, use a new disk for each validation run, and send the compact JSON
expected by the legacy `liveview` demo. A separate stress run briefly starved
a concurrent web test of memory; the final checks were run separately.

## Results

- Portable worker parking: latched bells, timer/clear/cancel and 2,000 races.
- Portable `blockportable`, `storagedeadlines`, `filesshutdown` and
  `appsessionmemory`, each on one and four workers. The memory contract
  exercises 3,000 events/owner calls/jobs/pane reads with explicit root and
  allocator-growth bounds.
- Portable SIGTERM and SIGINT on one/four workers: current-PID readiness,
  bounded drain/flush, readiness removal and durable replay in a fresh
  process.
- Portable HTTP/MVU: generated page, two independent cookie sessions,
  shared-model update, per-client deltas, server ticks, theme reshape and
  normal quit.
- Native connection/DNS contract on one/four workers: bounded resolver pool,
  abandonment/recovery, cancellation, nonblocking connect/read/write,
  duplicate adoption refusal, stale descriptor aliases, ownership checks,
  actor-death socket cleanup and refused connection cleanup.
- Native server: generated page, shared WebSocket model, client-state event,
  malformed/unknown message refusal without session loss, subscription
  start/stop, completed asynchronous job and a written durable journal.
  **100 concurrent sessions passed**, opening in 2.2 seconds; every client
  received the next shared update.

The separate **1,000-session native server test failed** on this guest.
The diagnostic run stopped opening session 611/1000. Before failure, the
server had 611 active sockets and about 3.49 GiB RSS; FreeBSD exhausted swap
and killed it with `failed to reclaim memory`. This is a measured capacity
failure, not a successful thousand-session result. The old README's historical
claim must not be used as a current capacity guarantee. Its memory cost
requires separate profiling before claiming comparable concurrency today.

Raw scripts, source manifests, native builds, test logs, kernel memory-failure
messages and final results are retained locally in
`.qos/validation/freebsd-20261018/`. VM state is under `.qos/freebsd-vm/`.
