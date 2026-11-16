# Spectre Native application parity and timing

## Application milestone

Run one serial Notes application from the same FP-RISC source on QOS Portable
and Native. Spectre already boots the integrated image from microSD and runs
two separately compiled applications with integer mailboxes. Use the existing
[cold-boot and application checks](../hal/spectre/actors/boot/README.md) as
regressions through these steps.

1. Move the [interrupt-driven UART](../hal/spectre/actors/uart/README.md) into
   the integrated keyboard endpoint. With every actor blocked, demonstrate
   WFI, wake on the first key, and delivery of the entire command.
2. Give a launched app a stable Files endpoint, a bounded text transfer, and a
   grant for its notes directory. Exercise a successful write, a refused
   write outside the grant, and a read after the other job slot is reused.
3. Launch Notes by QLog name, enter a line, save and exit. Power-cycle, reopen
   by name, and compare the exact text. Exercise the same app scenario on
   Portable. Keep the existing 54 MHz FPGA preset for this milestone.

## What a timing claim identifies

Use **(FP-RISC version, QOS Native version, Spectre version)** as the human
identifier. Resolve it to an immutable manifest for each result. Record the
compiler and runtime revisions separately, compiler binary, profile and flags,
kernel hash, application package hash, board sources, FPGA bitstream hash,
clock, memory configuration and loaded code address. The two job windows can
place identical code at different addresses. Capture toolchain and timing-model
versions, function or transaction boundaries, maximum input sizes, and initial
state assumptions alongside a bound. Keep each result attached to those inputs.

Start from an integrated build and run from the QOS checkout:

    python3 hal/spectre/actors/boot/timing-inputs.py /tmp/spectre-build hello

The tool checks the build manifest, compares the ELF payload with the packaged
application, and inventories linked main alongside the compiler segment report.
On the qualified hello image, main has 22 linked instruction sites, and
native-insns-v1 reports segmax=23, exittail=23 and ccalls=1. These numbers
answer different questions. The package builder inserts polls after compiler
analysis, the poll trampoline calls into the kernel, and hello writes to UART.
Timing main therefore requires following calls beyond those 22 sites.
The inventory leaves wcet_cycles unset.

## First cycle experiment

Choose a pure, bounded FP-RISC leaf such as a fixed-width bit-field transform.
Keep its result observable and check it against a reference. Specify the admitted
input range, no allocation or I/O, and every feasible branch. Inspect the final
RV32 instructions including any call to a compiler helper. Define separately
a leaf-only interval and an app-turn interval that includes polls and calls.

1. Add a measurement wrapper on the board around the linked routine. Read
   mcycle and minstret, calibrate an empty wrapper, and record raw deltas and
   the distribution of the empty measurement. Use rollover-safe reads on RV32.
   Buffer samples and print them after the interval. Capture return values,
   placement, interrupt policy and initial fuel. Measure the poll fast path
   and fuel exhaustion separately.
2. Exercise branch outcomes, warm and cold instruction/data state, SDRAM
   conflicts and refresh phases for the deployed configuration. Publish the
   largest **observed** cycles with the conditions and sample count. Consult
   the Simple-Risc counter probe and check its assumptions on this preset.
3. Derive conservative per-path costs from the actual core, memory controller
   and arbitration rules. Include hazards, fetch and data waits, multiply or
   divide if reachable, refresh, and bounded interrupt interference. Use
   justified loop limits and call targets on the linked control-flow graph.
   If any reachable wait, recursion, or indirect target lacks a bound, report
   that dependency. Validate the model with RTL traces and board samples.
   An observation above the prediction invalidates the model. Samples below
   the prediction supply validation evidence, not a proof of coverage.
4. Publish the first **conditional WCET** in cycles with the assumptions and
   supporting model. For the qualified nominal 54 MHz clock, 54,000 cycles
   equal 1 ms. Use the minimum guaranteed clock for a hard elapsed-time
   deadline. Keep measured maximum, modeled upper bound and deadline separate.

## From execution cost to application latency

Use the leaf model first for a bounded actor turn. Then model key arrival to
Notes consuming the byte and submitting an echo. Add interrupt handling,
wake-up, runnable actors ahead of Notes, their maximum time between yields,
mailbox backlog and service execution. State the permitted arrival rate and
runnable workload. A trusted app in a non-yielding native call can otherwise
delay the shell indefinitely. If the endpoint is the last byte leaving the UART,
include serialization and queued output too.

Treat save acknowledgement and durable save as separate endpoints. Bound file
size, QLog volume state and SD operations; a defensible deadline for physical
media completion needs a device latency guarantee. Until then report the
measured latency and specify the timeout/error path separately.

This applies the FP-RISC resource roadmap to the **54 MHz Spectre** deployment.
The earlier cached-SDRAM timing proposal has its own preset and assumptions.
See the FP-RISC checkout's
docs/2026-11-07-RESOURCE-CONTRACTS-WCET-AND-QOS-ROADMAP.md and the Simple-Risc
checkout's boards/tangnano20k/check_counters.py.

The [first physical leaf experiment](../hal/spectre/actors/boot/wcet-leaf/README.md) records the linked instruction bound, counter windows and remaining hardware timing assumptions.
