# A builtin-only, multi-board QOS: actors all the way down

Date: 2026-10-11. Kind: design proposal, for review before code changes.
Nothing here is built yet.

## Goal

QOS Native should be a real bare-metal system that depends on nothing but
itself: FP-RISC `profile builtin` code plus a few hundred lines of
per-board assembly. It should run on several boards (QEMU `virt` RV64, the
Tang Nano 20K's RV32 SimpleRisc core, later others), chosen at build time
through board support packages (BSPs). Base programs run on it unchanged,
compiled for a `riscv32-qos` or `riscv64-qos` target against one message
ABI that every board provides.

**Framing (2026-10-11): an exokernel of actors.** There is no kernel/user
split and there are no syscalls. The only mechanism is a small **actor
substrate**: actors, mailboxes, sending, activation, and turning hardware
events into messages. Everything an OS usually does in a kernel is done by
**OS services**: actors that each monopolize one resource, or one instance
of a resource (a hart's time, a RAM region, an interrupt line, a timer, a
UART, a block device). Programs get things done only by sending messages to
the services that own what they need. Messaging is designed to be fast,
non-blocking and customizable per actor.

This replaces an earlier draft of this document that proposed a microkernel
with an `ecall` syscall ABI.

## Where things stand

Today's Native is already halfway there: processes share the kernel's actor
plane (`qos/native/shared_boot.h`: `fpr_plane_actors_t`, the scheduler
contract) instead of crossing a syscall boundary. What it lacks:

- **The plane is not its own.**
  - The scheduler, channels, IRQ and timer routing, sleep and the memory
    actor are fprisc runtime C: `actors.c` (3,120 lines), `buddy.c` (370),
    `runtime.c` (3,233), plus `machine/virt`.
  - System and its services are Base actors built with the prelude
    (`programs/system.fpr`, `programs/mods/*`, `std/*`).
- **Resource ownership is implicit.**
  - Interrupts, timers and memory are routed by C (`Sys.irqBind`,
    `Sys.timerBind`, `Sys.arena`) rather than owned by addressable services.
  - Effects go through about 30 foreign primitives (`core/foreign.fpr`)
    rather than messages.
- **One board.** Native runs only on QEMU `virt`. Only
  `hal/virt/{plic,virtio,blockpolicy,netpolicy}.fpr` and fprisc's
  `machine/virt/clint.fpr` are builtin, and they are RV64-only (fprisc
  `machine/virt/virt.mk:18`). Board selection anywhere is a Makefile
  variable; there is no BSP or board-manifest concept.

Builtin already expresses the needed mechanism on RV64:

- typed layouts;
- MMIO and CSR access;
- an allocator (`machine/builtin/heap.fpr`);
- drivers (the PLIC, virtio and CLINT units);
- linearity checks, which this design uses for zero-copy buffer transfer.

## The substrate

The substrate is the only code every actor trusts and shares. It is builtin
(raw style: layouts, `Word`/`Addr`, no managed heap values) plus per-board
assembly. It contains **mechanism only**: no policy, no devices, no memory
management beyond its own fixed tables.

**Actors**
- An actor is a control block (a layout): its mailbox, its handler or its
  stack, its owning service's budget, and its hart affinity.
- An actor's address is its capability. Holding the address is the right to
  send to it. Addresses come only from spawning or from being sent one,
  never from arithmetic.
- There are two kinds:
  - **Handler actors** run one message to completion and keep no stack
    between messages. All services start as these. They are the fast path:
    activation is a function call.
  - **Stackful actors** have their own stack and can block in a selective
    `receive`. Base actors are these, so Base `receive` semantics are kept.
    Only they need a context switch.

**Mailboxes**
- A bounded ring of fixed-size message slots, sized per actor at spawn.
- A message is a small inline payload (a tag plus a few words), optionally
  with a linear **buffer transfer**: ownership of a memory region moves from
  sender to receiver with no copy, enforced by FP-RISC linearity in source
  and by an owner field in the region header at run time.

**Sending: never blocks**
- `send` writes a slot and returns `Accepted`, or the target's **overflow
  policy** applies.
- The policy is chosen per mailbox at spawn:
  - `Reject`: the sender gets `Full` and decides itself;
  - `DropOldest`;
  - `Coalesce`: replace a queued message with the same tag, which suits
    interrupts, timers and "state changed" notifications;
  - `Signal`: accept, but set a backpressure flag the receiver's owner can
    read.
- Same-hart sends are a ring write plus a run-queue link, a few tens of
  instructions with no trap.
- Cross-hart sends use per-sender single-producer rings, or one
  multi-producer ring with atomics, plus an IPI when the target hart is idle.

**Activation and scheduling**
- Each hart has a run queue of actors with pending messages.
- The *mechanism* is "run the next actor's next message".
- *Which* actor runs next is policy: a builtin function chosen per hart by
  the board manifest, and replaceable by a scheduler service that owns that
  hart (below).
- Preemption comes from the hart's timer. It matters only for stackful
  actors, since handlers run to completion within a budget.

**Hardware events become messages**
- Trap entry (BSP assembly) saves registers and calls the substrate.
- An interrupt posts a preallocated message to the actor that owns that
  line or timer, then returns to scheduling.
- Nothing allocates in trap context.
- A synchronous fault inside an actor is posted as a message to that
  actor's supervisor, and the actor stops.

**Bootstrap**
- At boot the substrate creates the service actors named by the board
  manifest and hands each one exclusive ownership of its resource.
- It then starts the root service (System), giving it those services'
  addresses.

The substrate has no names, files, sockets, processes or permissions. Those
are services.

## OS services

Each service monopolizes a resource, or an instance of one, and is the only
code that touches it. Services are actors like any other: they can be
replaced, restarted, multiplied (one per device instance), or bypassed by a
program that has been given a lower-level service's address. That last
point is the exokernel property: a program can talk to the raw block
service directly if it holds its address.

| Service | Owns | Written in |
|---|---|---|
| **Hart** (one per hart) | that hart's time: run-queue policy, budgets, idle and WFI | builtin |
| **Memory** | physical RAM regions; grants regions and gets them back when owners exit | builtin |
| **Interrupt controller** (one per PLIC or equivalent) | claim and complete; routes each line to the actor its owner registered | builtin |
| **Timer** (one per hart) | the hart's compare register; multiplexes deadlines into timeout messages | builtin |
| **Console/UART** (one per port) | a UART: receive and transmit queues, line discipline | builtin |
| **Block** (one per device) | virtio-blk, or SD over SPI on the Tang Nano | builtin |
| **Network** (one per interface) | virtio-net, or W5500 | builtin |
| **Display** | HDMI text or framebuffer | builtin |
| **Image** | code placement: places, zeroes, relocates and starts images | builtin |
| **System** (root) | names and capability distribution, launching, permissions, supervision | Base |
| **Store, log, files** | qlog and the file layer over a Block service | Base |
| **Apps** | their own state | Base |

Board drivers (`bbspi`, `oled`, `matrixkpd`, `ttp229` today) become
builtin services listed by the manifests of the boards that have them.

**Library OS.** The Base `std` client modules (`std/fs`, `std/net`,
`std/timer`, `std/uart`) become thin message protocols over these services.
An app that wants different behaviour (its own file layout, its own
buffering, polling instead of interrupts) uses a different library over the
same services, or talks to a lower-level service.

## Trust and protection

There is no hardware boundary. Protection is by language and capability:

- **Base code cannot forge addresses or touch memory directly.** It can only
  send to actor addresses it was given. System decides what each launched
  image receives.
- **Builtin code is trusted.** It can form any address and touch MMIO, so
  only the substrate, the builtin services and BSP code are builtin. Launched
  `.qa` images must be Base. Images are already hash-checked and gated by
  manifest (`mods/qaimg`, `manifest`, `loader/qaimg.c`).
- **Failure is contained by supervision.** A faulting or misbehaving actor
  is stopped and reported to its supervisor; services restart under System.
  A fault in builtin code is a system fault.
- **Hardware containment is an optional later layer.** PMP regions per
  image (SimpleRisc would need PMP) would contain buggy native code without
  changing the message ABI.

## The message ABI (`riscv32-qos`, `riscv64-qos`)

What a compiled image links against:

- the substrate operations: `send`, `spawn`, `self`, a selective `receive`
  for stackful actors, and buffer allocation, transfer and release from a
  region the Memory service granted;
- the message layout: a slot holds a tag and N words, fixed-width, with one
  layout per word size;
- the boot record an image's entry receives: its own address, its
  supervisor's, and the service addresses System granted.

Every effect a Base program has, file, network, clock or console, is a
message to a service. No other entry points exist. This replaces today's
`qos_shared_boot_t` plane tables and the `core/foreign.fpr` primitives on
Native. On Portable, `qosp` can implement the same substrate operations
with host threads and provide the services as host adapters, so one `.qa`
format per ISA serves both. `qos_hal_t`'s effect entries (`blk_*`, `net_*`,
`gfx_*`) become service protocols.

A Base image still links its own value runtime (`runtime.c`: values,
strings, ARC) for its own data. Actor scheduling is the substrate's alone;
images carry no scheduler of their own.

## Boards and selective compilation

```
substrate/        builtin: actor, mailbox, send, sched, trap, boot
services/         builtin: hart, memory, plic, clint/timer, uart16550,
                  uartsr (SimpleRisc), virtio, virtioblk, virtionet, image;
                  later sdspi, w5500, hdmitext
bsp/virt-rv64/            board.toml, crt0.S, trap.S, ctx.S, link.ld
bsp/tangnano20k-sdram/    (RV32, 8 MiB)
bsp/tangnano20k-bram/     (RV32, 64 KiB; probably substrate and services only)
userland/         Base: System, store/log/files, std clients, apps
```

A `bsp/<board>/board.toml` names:

- the ISA, the harts and the memory regions;
- every service instance: which service, its base address, its IRQ, and its
  mailbox size and overflow policy;
- the per-hart scheduling policy.

`make BOARD=<board>`:

1. generates `board.fpr`, builtin constants plus the bootstrap's service
   table;
2. compiles only the listed service units;
3. links that BSP's assembly.

The build system does the selection, so no language feature is needed at
first.

## Where today's code goes

| Today | Becomes |
|---|---|
| `actors.c` scheduler, channels, hart loop | `substrate/` (builtin) |
| `actors.c` IRQ and timer routing, `Sys.sleepUs` | interrupt-controller and timer services |
| `actors.c` memory actor, `buddy.c` | memory service |
| `loader/qaimg.c`, `process.c` placement, `Sys.placeImageAt` | image service |
| `machine/virt/crt0.S`, `ctx.S`, `hal.c`; `hal/virt/*.c` | `bsp/virt-rv64`; builtin services |
| `programs/system.fpr`, `mods/svc`, `ep`, `sysep` | System (Base): names, routing, launching |
| `mods/manifest`, `qaimg`, `qar`, `std/loader` | System policy; the image service only places |
| `mods/timer`, `uart`; `std/timer`, `uart`, `net`, `fs`, `blockio` | Base client protocols over services |
| `mods/qlog`, `files`, `blockep` | Base store and log services over a Block service |
| `core/foreign.fpr` effect primitives, `qos_shared_boot_t` | messages to services; the substrate message ABI |
| apps, UI, graphics, live tooling | unchanged Base apps |

## Prerequisites

**In fprisc:**

1. **`--raw` and `--export` on RV32,** and a substrate entry callable from
   BSP trap assembly (today: `Compile.hs:409`, `:966`).
2. **Multi-unit builtin builds.** No builtin program uses `use` today.
3. **A raw image that links without `runtime.c`.** `BUILTIN_RT` links it
   today (`Makefile:213`).
4. **32-bit atomics and fences, and CSR primitives on SimpleRisc.**
   `machine/builtin/tangnano20k/machine.c` panics on them today.
5. **Base codegen that targets the substrate's `send`/`receive`/`spawn`**
   instead of `actors.c`, and a linear buffer-transfer type in the prelude.

**In SimpleRisc (HaskPlayground):**

- The A extension, for multi-producer rings. Single-hart boards can use
  IRQ masking instead.
- Running Base images on the Tang Nano also depends on Base on RV32
  (64-bit `Int`, software floats). That is a separate track.

## Phases

Each phase ends running on both `virt-rv64` and `tangnano20k-sdram`.

1. **Prerequisites 1–3.** Exit: a two-unit raw program with an exported
   entry links without `runtime.c` and runs on RV32 and RV64.
2. **Substrate skeleton.** Handler actors, mailboxes with every overflow
   policy, single-hart scheduling, trap-to-message, and the UART, timer and
   interrupt-controller services from manifests. Exit: an interrupt-driven
   echo actor and a periodic timer actor on both boards, plus a benchmark of
   same-hart send-to-activation in instructions.
3. **Stackful actors and the memory and image services.** Selective
   `receive`, context switching, buffer transfer and region grants.
4. **Base on the substrate.** Retarget Base actor codegen (prerequisite 5),
   then run a Base app on `virt` that reaches only the services it was
   given. Exit: today's Native test apps run with no `foreign.fpr` effect
   primitives.
5. **System as the root service.** Names, launching, supervision and the
   store services in Base. Exit: feature parity with today's Native on
   `virt`; then retire the old build.
6. **Board services.** SD over SPI, then W5500, then the HDMI text console
   on the Tang Nano. Multi-hart scheduling on `virt`.

## Risks and open questions

- **Language-based protection** is only as strong as the rule that launched
  images are Base. A future "native plugin" path needs PMP or a verifier.
- **Builtin expressiveness.** There are no closures or indirect calls under
  `--raw`, so handler dispatch inside services is `case` over message tags.
  The substrate itself must call handlers indirectly; this is the one
  indirect call the compiler or BSP assembly has to provide.
- **Fairness without syscalls.** A hostile or buggy actor can flood
  mailboxes. Overflow policies and per-service budgets enforced by the hart
  service are the answer. Defaults need care.
- **Selective receive cost** for stackful Base actors on long mailboxes.
  Keep per-tag indexes, or encourage handler-style Base actors.
- **The C-reduction plan** keeps the scheduler and rings in C ("The line").
  This design moves them into builtin and keeps only trap entry and the
  context switch in assembly; that plan should be updated if this is
  accepted.
- **The 64 KiB BRAM board** probably fits only the substrate and builtin
  services, not Base images. `tangnano20k-sdram` is the first real RV32
  target.
