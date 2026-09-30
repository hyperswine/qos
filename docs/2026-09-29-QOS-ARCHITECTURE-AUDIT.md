# QOS against the minimalist actor OS ideal

Date: 2026-09-29. Kind: source audit, with selected fresh Portable checks.

Audited QOS revision: `28d69c85e83b7b3c36cb32e7b821b46e2da9bc3d`.
FP-RISC dependency: `6f3e428631e72a83da3cb538915391d3f39ed42e`.
This is a dated assessment, not a replacement specification. No runtime fixes
are made by this report. Earlier accounts remain historical.

## Assessment

QOS has substantial pieces of the intended system: ordinary FP-RISC service
actors, per-hart ACB scheduling, weighted admission with aging, message-driven
UART and timer protocols, a URL-keyed storage log, a namespace-oriented shell,
and a small host interface capable of running independently loaded applications.
These are working implementation foundations, not just design notes.

It is not yet one uniform reference OS built from those primitives. Native
System routing, the Portable shell namespace, direct HAL calls, and the newer
Files/Loader services implement overlapping contracts. There is no common
open/read/write/close connection protocol that all these paths obey. Some I/O
blocks a scheduler worker; permissions and device ownership are enforced only
on particular paths; native process loading still has one image slot. Portable
multi-app execution works in the selected check, but that does not establish a
multi-application graphics desktop or the same capability on native QOS.

The greatest architectural work is convergence: make the existing pieces share
one endpoint, ownership, lifecycle, and completion model. Adding more special
routes would increase the distance from the intended design.

## The intended contract

The audit uses the user's stated ideal, rather than treating old documentation
or current implementation limitations as requirements:

- URLs name logical resources and services. `/dev/display` and `/dev/display/0`
  need not be directory/inode objects; a UNIX-like shell can interpret namespace
  prefixes without making a hierarchical filesystem the kernel's object model.
- Open establishes a bidirectional service connection, with System resolving
  and authorizing it. Read/write/close operate on that connection; subsequent
  traffic can go directly between its endpoints. Seek, ioctl, sockets, and
  resource-specific controls are library protocols, not new kernel primitives.
- Effects use asynchronous messages and completions. Waiting for a reply may
  park an actor, but must not hold a scheduler worker while the device waits.
- ACBs are the scheduling unit. Per-hart queues, stealing, weighted selection,
  and an explicit aging bound remain simple and understandable.
- A service owns its driver and delegates devices to actors. FP-RISC expresses
  service policy; C exposes small HAL operations where hardware access is needed.
- Boot establishes the machine/HAL/runtime and hands policy to services. Portable
  hosts the same essential contracts on macOS/Linux. Multiple full applications
  share services and resources with defined lifetimes.

## Implementation map

| Area | Current implementation | Fit |
|---|---|---|
| Native boot | FP-RISC machine startup enters runtime, then `programs/system.fpr` starts UART, timer and optional storage, loads configuration and launches startup | Real FP-RISC bootstrap, but not a general service graph |
| Native URL I/O | `programs/mods/svc.fpr` grants and hardcoded route dispatch | Partial; predominantly read/write, no uniform connection lifecycle |
| Portable namespace | `programs/mods/qsys.fpr`, `appkit.fpr`, `cliapp.fpr` | Logical paths and actor-backed files; mediated, kind-specific operations |
| Storage | `qlog.fpr` actor and `std/fs.fpr` client | Strong single-writer direction; raw block access remains available |
| App service | `std/loader.fpr` attaches images and uses `Sys.spawnApp` | Real separate app PIDs on Portable; fixed, matched image slots |
| Scheduling | Sibling `fprisc/runtime/actors.c` | Per-hart queues with weighted/aged admission; global donation FIFO remains |
| Memory | Runtime buddy allocator plus privileged C memory actor | Actor integration, not an independently booted FP-RISC `Memory.qa` |
| Drivers | FP-RISC UART/timer/graphics actors plus C device tiers | Mixed abstraction depth and ownership |
| Portable host | `qos/portable/qosp.fpr`, C host and HAL table | Good policy/mechanism split; platform libraries and compiler remain dependencies |
| Full apps | Terra II and other MVU programs | Substantial app code; simultaneous shared graphics/resource arbitration not established |

Source entry points: [System](../programs/system.fpr), [Svc](../programs/mods/svc.fpr),
[QSys](../programs/mods/qsys.fpr), [Files client](../std/fs.fpr),
[Loader](../std/loader.fpr), [Portable policy](../qos/portable/qosp.fpr),
[Portable host](../qos/portable/host.c), [HAL ABI](../qos/appside/qos_abi.h),
[scheduler](../../fprisc/runtime/actors.c).

## URLs, namespace, and the four operations

### The namespace idea is present

QSys stores entries as `(path, kind, owner)` and resolves exact path strings.
The CLI's `ls [prefix]` filters the namespace; it does not need a tree of actual
directories. Storage records are named by strings/URLs. This is close to the
intended separation between naming and conventional filesystem presentation.

However, there are several different naming mechanisms, rather than a single
endpoint resolver. Native Svc dispatch tests `/services/display`, keyboard,
clock, modules, storage, uart, timer and `/pins` prefixes. QSys has its own
registry and VFS entries. Raw devices use `device "uart"` or `device "blk"`.
The default routes inspected do not establish the proposed `/dev/display/0`
model. Renaming paths alone would not unify their behavior.

Svc's permission prefix check correctly requires a slash boundary: a grant for
`/pins` does not cover `/pinstripe`. The remaining problem is the limited reach
of that gate, not an indiscriminate string-prefix comparison.

### Open and close are missing as universal semantics

`Svc` exposes read/write routing. QSys exposes `Read`, `Write`, and `VfsList`:
service entries return descriptive text on read, and only file-kind entries
accept VFS writes. Files forwards each operation to the per-file actor; VFS
waits for that forwarded reply and sends it back to the client. A file actor
is created lazily and retains a cached body. There is no shared connection
object with open/close, per-client lifetime, cancellation and cleanup.

`svcLookup` can return an actor handle, so direct discovery exists in one path.
It is not yet an authorized open handshake applied consistently to resources.
UART's linear phase-typed library has open/close, but those are UART-specific.
The Files library instead exposes latest/append/replay/delete/stats/compact.
Such richer library operations are compatible with the ideal if they sit above
one transport contract; today these are separate transports and conventions.

The HAL ABI also has explicit network, block, graphics, sound and device entries.
Host sockets/ioctls inside a C platform adapter are not intrinsically a design
violation. The gap is that applications can reach specialized effect surfaces
without going through the intended URL connection abstraction.

Evidence: [CLI](../programs/mods/cliapp.fpr) `clLs`,
[QSys](../programs/mods/qsys.fpr) `vfsServeOne`, `vfsWriteOne`, `relay`, `filesFwd`,
[Svc](../programs/mods/svc.fpr) `prefixOf`, `covered`, `dispatch`,
[UART client](../std/uart.fpr), [foreign surface](../core/foreign.fpr).

## Nonblocking IPC and I/O

### Actor waiting mostly has the right underlying mechanism

The runtime parks an actor in `block_unless` and resumes the scheduler. Receive
and parked `Sys.sleepUs` therefore need not block a host thread or hart. Native
shared-plane storage calls use the calling ACB to await the service reply;
the dormant-mailbox spin is a legacy fallback, not the entire current design.

The timer route is a useful positive example: a write schedules `TAfter`, returns,
and a later `TFire` goes directly to the calling actor. UART queues TX and uses
interrupt messages on native; subscribers can receive RX messages. Portable
network writes use nonblocking descriptors and queue an unwritten tail on
`EAGAIN`. The ABI comment describing network writes as blocking-full is stale.

### Worker-blocking operations remain

Native `hal/virt/blk.c` submits a request and spins up to 40,000,000 iterations
waiting for the used queue to advance. Portable `blk_raw.c` calls synchronous
`pread`/`pwrite`. Putting these calls inside a storage actor serializes ownership,
but does not turn the device wait into an actor suspension. That worker cannot
run another actor during the call. Portable console output also calls host
`write`; a blocked pipe can stall that path.

Thus “all effects are nonblocking message passing” is not yet an end-to-end
property. It requires asynchronous HAL completion, or dedicated host I/O workers
that report completion by message while scheduler workers remain available.
Graphics submission and other foreign calls likewise need explicit execution
budgets; compiler yield points cannot preempt an arbitrary C call.

### Protocol correctness needs attention

Many helpers do `_ = send ...; receive...` without checking the send result.
Static mailboxes can refuse messages. A caller can then wait for a reply to a
request that was never accepted. Dynamic mailboxes reduce capacity refusals but
do not eliminate dead-recipient or allocation failure behavior.

QSys and AppKit's `call` use plain `receive me`, so an unrelated event already
in the mailbox can be consumed as the RPC result. `receiveFrom` improves sender
selection but does not correlate multiple outstanding requests to one service.
These shortcuts are particularly troublesome when timer/input/subscription
events are deliberately asynchronous. The mediated VFS/Files loops also stop
serving new requests while awaiting a downstream reply: actor-level
head-of-line blocking, even though the worker remains free.

Define accepted/refused send results, request IDs or dedicated reply endpoints,
completion/error messages, and close/cancellation behavior once. These are
small protocol rules rather than a reason to add a complex blocking subsystem.

Evidence: [runtime](../../fprisc/runtime/actors.c) `block_unless`, `a_sleep_us`,
[native storage trampoline](../loader/process.c) `qos_store_call`,
[native disk](../hal/virt/blk.c), [host disk](../hal/unix/blk_raw.c),
[host networking](../hal/unix/net_raw.c) `qos_netraw_write`,
[QSys](../programs/mods/qsys.fpr) `call`, `rpc`,
[AppKit](../programs/mods/appkit.fpr) `call`.

## Scheduling and bounds

The fundamental scheduling unit is an ACB, including native application actors
on the shared scheduler plane. Each hart has a backlog and FIFO run queue.
The default admission selection is a weighted reservoir scan driven by a
per-hart LCG. Old or privileged actors take precedence. This substantially
matches the proposed simple randomized weighted scheduler.

There are important qualifications:

- `FPR_TAU = 64` measures machine-wide admissions, not microseconds. Run queue
  refill defaults to four actors. A backlog selection scans the list, so the
  cost grows with ready actors; it is not constant-time scheduling.
- Work redistribution donates oldest actors when backlog exceeds four into a
  **global 64-entry FIFO protected by `steal_lock`**. Idle harts take from that
  FIFO. There is no single global dispatcher, but there is global scheduling
  state, a shared lock, and a global admission counter. This is donation-based
  stealing, not independent victim-queue stealing.
- Aging expresses an admission fairness policy. A wall-clock upper bound also
  needs bounds on runnable population, scheduler overhead, each execution slice,
  locks, interrupts, foreign calls and device completion. The source comment's
  `tau` in admissions cannot by itself establish a target-time WCET.
- Cooperative yielding and parked receive are meaningful, but synchronous
  disk/foreign work invalidates an unconditional bounded-slice claim.

Keep the weighted/aged policy if desired. Decide explicitly whether the shared
donation FIFO is acceptable. The implementation is already simple enough to
reason about structurally; its timing claim should be stated as conditional
until the execution and I/O bounds are actually enforced.

Evidence: [actors.c](../../fprisc/runtime/actors.c), scheduler block around lines
710–892 (`donate`, `steal`, `select_backlog`, `refill`), and
[native process entry](../qos/native/proc_entry.c).

## Driver ownership, HAL, and boot

UART is a strong starting point: an FP-RISC actor has an owner, configuration
state, a bounded outgoing buffer, RX subscribers and interrupt handling.
`std/uart.fpr` supplies linear phase-typed client handles. Timer and `glsvc`
also express useful service protocols in FP-RISC.

The current UART implementation is tied to `device "uart"`, 16550 register
offsets and QEMU IRQ 10. It performs `reg8` access and bit tests in FP-RISC.
It is not an N-device factory receiving abstract HAL device handles. Native
System also uses the same UART for direct console/keyboard paths while its
UART service is unarmed and shared. “One service exclusively owns the driver”
is therefore a convention with exceptions, not a universal invariant.

Likewise, QLog is a single writer when consumers use its service, but the
application HAL still exposes block read/write. Portable passes a common HAL
table plus a serialized grant blob; the raw device wrapper checks whether the
table supports a device, not whether the calling actor owns a particular URL
grant. QSys explicitly does not enforce the process permission gate. Native
process entry also describes its grants as an FP-RISC-side gate without
hardware isolation. This is a trusted/cooperative system, not an enforced
service-ownership boundary across every effect path.

Boot is reasonably small at the machine level: stack/CPU setup, BSS/runtime
initialization and hart startup lead into an FP-RISC program. System then owns
manifest/grant policy, launch UI, configuration and route setup. It starts
UART/timer/storage, rather than loading a general set of independent System,
Memory, Files and Graphics service images.

Memory has a real runtime actor, pinned to hart 0 with priority. Allocation
also has an inline `buddy_alloc_try` fast path and direct fallbacks. This is not
yet an FP-RISC `Memory.qa` through which every allocation request must pass.
That is a deliberate implementation choice to assess, not evidence that memory
management has no actor model at all.

The Portable policy/mechanism split is a notable strength: `qosp.fpr` handles
archive and manifest policy, while C supplies image placement/protection,
thread entry and platform device functions. It is self-contained as a host
process in that sense, but builds still consume the sibling FP-RISC compiler
and runtime, and graphical variants need platform graphics/audio libraries.

Evidence: [UART](../programs/mods/uart.fpr), [System](../programs/system.fpr)
`main`, `spawnUart`, [GL service](../programs/mods/glsvc.fpr),
[device wrapper](../qos/appside/hal.c) `h_device`,
[host table](../qos/portable/haltab.c), [machine startup](../../fprisc/machine/virt/crt0.S),
[runtime memory](../../fprisc/runtime/actors.c) `fpr_mem_take`, `fpr_mem_spawn`.

## Applications and lifecycle

Portable supports more than “one application can ever run.” It loads one outer
image, but that image can host Files/Loader and attach additional app images.
`std/loader.fpr` finds an `app` export, detaches its temporary module registry
entry while retaining the code window, and spawns it with a fresh PID. Child
actors inherit that PID. The fresh two-app check passed below.

These plugins are linked against the outer image's exported absolute addresses
and carry a matching shell stamp. Slots are chosen at build time. This is useful
in-process multi-app support, but not independent relocation of arbitrary apps
into independently protected address spaces. A PID does not itself provide
memory or driver isolation.

Native shared-plane scheduling is also real: process actors use the kernel's
per-hart queues. Its loader nevertheless has one `_proc_arena_start/end` slot
and a `g_shared_live` gate. Multiple native process images cannot currently
coexist through that launcher. Root exit clears the gate; the inspected exit
path does not establish that all child actors have stopped executing that image
before reuse. The lifecycle must account for the entire image's live users.

Terra II is a substantial FP-RISC MVU application. Its main creates its own GL
service and optional Files service. The C graphics tier has a shared graphics
state/window. One render actor serializes one application's rendering, but
starting another such actor is not a compositor or input/resource arbitration
policy. The selected app test does not prove that Terra II and another full
graphical app can run together safely. That needs a shared Graphics service,
session/resource ownership and a simultaneous-app acceptance test.

Evidence: [Loader](../std/loader.fpr) `lStart`, `lRun`,
[plugin build contract](../qos-app.mk), [host plugin loader](../qos/portable/host.c),
[native loader](../loader/process.c), [native exit](../qos/native/proc_entry.c),
[Terra II](../programs/terra2.fpr) `main`, [graphics](../hal/unix/gfx.c).

## Concrete correctness findings

These are source-confirmed control-flow findings. They were not exercised by
failure-injection or native hardware tests in this audit, and remain unfixed.

| Priority | Finding and consequence | Source / acceptance for a fix |
|---|---|---|
| High | Native image placement happens before the live-slot check. A second valid placement attempt can overwrite a running image before returning “a process is still running.” The normal launcher may serialize requests, but this loader guard does not protect its own boundary. | `loader/process.c:g_sys_place_image_at`, around 202–225; `loader/qaimg.c:fpr_qaimg_place` copies/zeros memory. Reject an occupied slot before any write or static-window change; verify running code and data remain unchanged. |
| High | Native root exit marks the slot reusable without demonstrating image-wide quiescence. Surviving child actors can retain code/data references into the old image. | `qos/native/proc_entry.c:proc_root`, `loader/process.c:shared_on_exit`. Keep the image live until all actors/references using it have ended, or enforce and test structured shutdown. |
| High | RPC helpers ignore send refusal; QSys/AppKit also accept an arbitrary next message as the reply. Saturation/death can strand a caller; mixed event/RPC traffic can consume the wrong message. | `qsys.fpr:call/rpc`, `appkit.fpr:call`, `std/fs.fpr:rpc`, Loader clients. Test refused sends, a dead service, and an unrelated queued event. |
| Medium | `fileWr` appends to its cached body after either `Ok` or `Err` from storage. A failed write becomes visible in memory despite the failure reply, then disappears after restart. | `qsys.fpr:fileWr`, around 199–207. Only update the cache on success; inject an `Err` and verify subsequent read is unchanged. |
| Medium | Loader persistence is not transactional with its success reply. `lManifest` drops the result of `FS.append`; `lLive` still reports success and adopts the new chain. | `std/loader.fpr:lLive/lManifest`. On a failed manifest append, report failure and define rollback or explicit nonpersistent state; test reboot behavior. |

The last two findings are especially relevant to the compositional model:
services must expose honest outcomes, or higher layers cannot build reliable
semantics from them. Endpoint ownership and nonblocking HAL work are larger
architectural gaps, separate from these localized correctness defects.

## Fresh verification and its limits

Built a new headless Portable host and new AArch64 app/plugin images on macOS,
using the current compiler executable. Outputs, generated units, disk and logs
were placed under `/tmp/qos-audit-20260929`; `XDG_CACHE_HOME` was redirected there.
The first host build hit the sandbox's default-cache restriction; rebuilding
with that temporary cache succeeded. App builds used `make -o fpr` to use the
existing compiler instead of rebuilding it. No full regression suite was run.

| Check | Fresh outcome | What this establishes |
|---|---|---|
| `make -C qos portable QOSP_OUT=...` | Passed | Current headless host compiles |
| `tests/apps.fpr` plus `appa` slot 0 and `appb` slot 1, temporary QLog disk | `APPS HOLD`: appa PID 1, result 9006000; appb PID 2, helper PID 2, result 42; shell PID 0 | Both images launch and report through actors; appb child inherits PID; test checks at least 97% free-memory recovery |
| `tests/timerroute.fpr` | `timerroute: write=ok fire=ok` | Routed asynchronous timer completion on Portable |
| `tests/uartroute.fpr`, stdin `hi` | `uartroute: wrote 15B via /services/uart; rx="hi"` | Routed UART transmit/receive on the Portable backend |

The apps test launches two images without waiting for their completion between
launch requests, but does not assert a minimum interval of overlap or sustained
fairness under load. Appa's “helper PID” report is its own PID; appb is the case
that actually spawns and checks a helper. Neither this test nor the timer test
proves a worst-case latency bound.

Reproduction uses the existing targets, with `BUILD`, `QA_OUT`, `PLUG_OUT` and
`QOSP_OUT` directed to temporary paths: build `tests/apps.fpr`, run `plugsyms`,
build `tests/appa.fpr` with `PLUGSLOT=0` and `tests/appb.fpr` with `PLUGSLOT=1`,
seed them with `tools/mkdisk.py`, then run the host with `FPR_DISK` naming that
disk. Route tests are ordinary `qos-app` builds run by the same host.

Existing native process/spawn-steal, mailbox and memory checks in
[check-all.sh](../check-all.sh) were inspected, not rerun. Native QEMU boot,
hardware IRQs, Linux graphics, GUI interaction, Terra II visual behavior,
multiple graphical applications, exhaustion, persistent-write failures and
formal schedulability remain unverified here.

## Recommended convergence order

1. Fix the concrete loader, RPC and persistence findings, with failure-path
   regression checks. They undermine the existing abstractions independently
   of a larger redesign.
2. Specify one typed endpoint protocol: URL resolution and authorization at
   open, direct bidirectional traffic after open, read/write completion, close,
   cancellation, refusal and peer death. Keep resource-specific controls as
   library messages or named endpoints. Clarify whether directory-like reads
   are a namespace service convention, rather than a core object type.
3. Migrate both native Svc and Portable QSys to that contract. Prove a service
   can register a new URL without adding a central dispatch branch, and that
   post-open traffic need not traverse System or VFS.
4. Make a driver service the sole holder of raw device authority. Inject HAL
   device handles; instantiate one actor per device; route console, file and
   application clients through those owners. Choose explicitly whether this is
   enforced capability safety or a trusted-program convention.
5. Replace worker-blocking I/O with submission/completion paths. Test a stalled
   disk while unrelated actors continue on the same scheduler worker. Bound
   queue growth and define overload outcomes rather than silently waiting.
6. State scheduler guarantees in both admission and time units, with target
   assumptions. Decide whether to retain global donation or use decentralized
   stealing. Measure and bound scheduler overhead, foreign calls and service
   work before making WCET claims.
7. Generalize native image lifetime/allocation and Portable app services. Boot
   a shared Files/Graphics/input setup; run Terra II alongside another real app;
   close/restart either while the other continues, then verify resource and
   memory reclamation. Preserve the simple ACB model while doing so.

This path retains the strongest existing code. The desired reference OS is
plausible from this foundation, but uniform asynchronous endpoints, exclusive
ownership and application lifetime must become actual shared contracts before
QOS can be described as implementing the whole ideal.


## 2026-09-30 follow-up: one memory model, without image slots

The clarified ideal is a flat usable memory space managed by Memory.qa through
one global power-of-two buddy allocator. Actors receive memory grants and manage
local allocations, typically with slabs. A static actor declares a fixed budget;
a dynamic actor declares an initial allocation that can grow. Code and static
data should consume ordinary managed memory too, without a separate fixed-slot
process model. These are intended semantics, not current guarantees.

### Why slots exist today

The slots discussed above are predetermined **executable-image addresses**, not
actor slab grants or buddy blocks. Native images are linked for the reserved
process arena. Portable plugins are linked at selected addresses, and references
to the outer image's runtime/module symbols use its absolute symbol addresses.
`PLUGSLOT` selects a plugin address; shell stamps enforce the matched build set.
This avoids general relocation at load time, but introduces fixed placement,
image-slot limits and rebuild coupling. Slots are a loader implementation
constraint, not a requirement of the proposed memory architecture.

Evidence: [native placement](../loader/process.c) `g_sys_place_image_at`,
[Portable image layout](../qos/appside/link-qosapp-a64.ld),
[plugin linking](../qos-app.mk), [host placement](../qos/portable/host.c).

Removing them requires position-independent code or relocation support, plus a
symbol-binding contract that does not depend on one exact shell image's linked
addresses. The loader can then request blocks from Memory.qa, place code/data,
resolve references, apply any platform execution permissions/cache maintenance,
and launch actors. A shared flat address space is compatible with executable
page permissions on Portable; it does not require all memory to be writable code.

### Existing allocator versus the intended contract

The runtime already has buddy allocation and actor-local slab pools. However:

- `std.actor`'s existing `Static n`/`Dynamic n` control mailbox capacity **per
  sender channel**, not total actor memory. They must not be documented as actor
  reservation/growth contracts. A separate actor-memory contract is needed,
  including whether stack, mailbox, metadata and shared-message charges count.
- General small-object recycling uses size-class buckets; it is not uniformly
  one slab per FP-RISC type.
- A C memory actor coexists with direct buddy fast paths and fallbacks. Memory.qa
  is not currently the exclusive FP-RISC owner of every allocation decision.
- Power-of-two blocks are split/coalesced as needed. Prepartitioning establishes
  managed roots/alignment; it need not permanently assign fixed regions to actors.

See [actor mailbox API](../../fprisc/std/actor.fpr),
[actor allocation](../../fprisc/runtime/actors.c) `fpr_mem_take`,
[slab pools](../../fprisc/runtime/runtime.c),
[buddy allocator](../../fprisc/runtime/buddy.c).

The intended ordinary path is: allocate small values from an actor's local slab;
request another block only when growth is needed; refuse growth for a static
budget; return blocks when ownership permits. Define whether a static declaration
reserves memory at spawn or merely caps later use, and define explicit allocation
failure outcomes. A dynamic allocation is not an unlimited guarantee.

Shared code must remain allocated while any actor can execute it, and shared
message storage must remain alive while another actor holds it. These require
ownership/lifetime accounting, but not a separate slot mechanism. Memory.qa and
its request/completion path also need bounded bootstrap storage so they can
operate under exhaustion without recursively requesting memory from themselves.

## 2026-09-30 follow-up: replacing C with bare-metal FP-RISC

Most OS policy and service state machines could be expressed in FP-RISC. A
smaller low-level layer can expose hardware operations and the primitives needed
to execute FP-RISC itself. The aim is consistent ownership and small interfaces,
not translating C line-for-line or increasing runtime complexity to eliminate C.

A source inventory of the inspected QOS implementation directories found about
6,100 physical lines of C, excluding host tests and headers. The sibling FP-RISC
runtime contained about 6,600 lines, with about 2,900 more across machine backends.
These counts include comments and alternative platforms; they are not linked
kernel sizes. Inspected revisions remain those at the start of this report.

A rough engineering estimate is that **40–60% of the inspected QOS C could move
to FP-RISC without rewriting the language runtime**. This is a qualitative
migration estimate, not a measured removable-line count or completed prototype.
It does not apply to the additional FP-RISC runtime/machine totals.

| Area | Candidate FP-RISC responsibility | Initial low-level boundary |
|---|---|---|
| Memory | Budgets, grants, growth/refusal, ownership; potentially buddy policy | Raw storage, alignment, bootstrap allocation |
| Scheduler | Weighted selection, aging, queue policy and stealing decisions | Context switches, atomics, fences, interrupt entry |
| Drivers | State machines, buffering, requests and completion handling | MMIO, DMA submission, interrupt acknowledgement |
| Networking | Parsing and ARP/IP/TCP protocol state | NIC descriptors and frame transfer |
| Loader | Resolution, validation, relocation policy and image lifetime | Copy/protect code, cache synchronization |
| Graphics | Scene traversal, sorting, batching and resource ownership | GPU calls and platform context management |
| Portable host | Remaining service policy and protocol handling | POSIX threads, mappings, platform I/O and C-library bindings |

This distinction is concrete: [native networking](../hal/virt/net.c) combines
virtio device access with a limited transport implementation, while
[graphics](../hal/unix/gfx.c) combines scene traversal/sorting/render preparation
with GPU operations. Both contain policy above the hardware boundary. Moving
network protocol code would not by itself make the current limited transport a
complete TCP implementation. Host adapter calls remain necessary for Portable.

The language runtime is harder to replace. Allocator, message representation,
reference counting and actor machinery are prerequisites for ordinary FP-RISC
execution. Implementing them in FP-RISC requires a restricted execution path
with explicit raw-storage operations and bounded/no-allocation behavior where
needed. It cannot silently depend on the very services being implemented.

Memory.qa can first own grant policy while the existing roughly 360-line buddy
allocator remains a low-level primitive. Small object allocation stays local;
block requests cross the service boundary. This offers more architectural value
than translating the allocator first. Similarly, per-hart scheduler logic must
not gain an allocation dependency or centralized actor bottleneck merely because
its implementation language changes.

Recommended direction: put nearly all QOS **semantics** in FP-RISC, retain a
compact runtime/HAL, and migrate one ownership boundary at a time with equivalent
behavior and failure-path checks. Bootstrap storage, atomic access, hardware
completion and executable-code lifetime remain necessary mechanisms in either
language. No C replacement was implemented or benchmarked in this follow-up.

## 2026-09-30: the concrete correctness findings are fixed

All five rows of [Concrete correctness findings](#concrete-correctness-findings)
are fixed, each with a failure-path test: RPC refusal, death and
correlation; `fileWr`; `lManifest`; placement before the live-slot check;
root-exit quiescence. See [FAILURE-HONESTY](2026-09-30-FAILURE-HONESTY.md).
That page also records what remains: `svc.storeRpc`'s `receiveRes`, and
references into an old image that outlive its actors.
