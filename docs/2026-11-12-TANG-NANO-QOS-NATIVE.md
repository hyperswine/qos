# Porting QOS Native to the Tang Nano 20K

**Proposal, 12 November 2026.** Target the existing simple-risc `fprisc-84` image. The first deliverable is a single-hart QOS Native image in SDRAM that runs two actors, wakes a sleeping actor on a timer, and delivers a UART receive interrupt to an actor. Acceptance requires a physical board run.

The recorded hardware baseline is RV32IM at 84 MHz with SDRAM at 48 MHz. Build `28ed47fb2abb9afc` passed the physical instruction checks and all seven FP-RISC example suite cases. Machine-mode traps, direct `mtvec`, `MRET`, `WFI`, timer and external interrupt support give us a starting point for kernel bring-up. The Base suite exercised a single-threaded runtime. QOS scheduler and process execution on this board remain unverified. [Board qualification](../../simple-risc/docs/2026-11-08-FPRISC-84.md) · [Core and devices](../../simple-risc/src/SimpleRisc.hs)

The source assessment used QOS `0e2cdb9`, simple-risc `8f83a6d`, and FP-RISC checkout `69d893a0`. QOS pins FP-RISC `e138e654`. Start with that pin and record the compiler actually used in every build. The board suite used an earlier compiler. The October multi-board proposal describes the longer-term actor service architecture. This port can use the existing scheduler and machine/device split to test it incrementally. [Compiler pin](../fprisc.lock.json) · [Multi-board proposal](2026-10-11-BUILTIN-KERNEL.md) · [Native HAL](../hal/virt/qos-virt.mk)

## 1. Boot and return from a machine interrupt

Add a Tang Nano Native build target for RV32IM, ILP32 and one hart. Reuse the board ROM upload protocol, SDRAM entry address and UART routines. Adapt startup to initialize the stack and global pointer, clear BSS, install a machine trap vector and establish scheduler-safe interrupt state. Verify the timer register map and tick rate on the actual preset, including safe RV32 access to the split 64-bit timer and compare registers. [Tang Nano machine](../../fprisc/machine/tangnano20k/README.md) · [Existing machine startup](../../fprisc/machine/virt/crt0.S)

Replace the virt linker's 128 MiB RAM assumption with 8 MiB at `0x80000000`. Keep the ROM's 2 MiB upload limit separate from runtime consumption. Produce a link map showing loadable bytes, BSS, boot and actor stacks, allocator bounds and free RAM. Check the binary ISA and inspect unresolved helpers before upload. [Virt linker script](../../fprisc/machine/virt/link.ld)

**Board gate.** Upload through the ROM, print a build identifier, arm the timer twice, and report two handler entries and successful returns to foreground code. Capture the image hash, map, board identity and UART transcript.

## 2. Run the single-hart actor scheduler

Link the real allocation, actor and context-switch paths into the small image early. Inspect the linked instructions and atomic helper references. The RV32IM core lacks the A extension, while actor state and queues use atomic read-modify-write operations. For operations that only race with a local interrupt, evaluate short critical sections that save and restore the prior interrupt-enable state and preserve the required compiler/memory ordering. Audit each blocking or reentrant path separately. A lock that waits for a preempted owner cannot make progress with interrupts masked. Check the RV32 trap frame, stack alignment and register preservation across both voluntary yield and interrupt return. [Actor runtime](../../fprisc/runtime/actors.c) · [Context switch](../../fprisc/machine/virt/ctx.S)

**Board gate.** Two actors exchange numbered messages through repeated fuel yields. One sleeps and wakes on a timer while the other makes progress. Check ordering, counts and register sentinels, including interrupt arrival during scheduler activity. Record stack and heap use. Revisit FPGA atomics only if the software audit identifies an operation the single-hart implementation cannot safely provide.

## 3. Deliver board devices through the QOS HAL

Keep boot, context switching and timer primitives in FP-RISC's machine layer. Put program-visible device registration and IRQ delivery in QOS. Start with the console and UART RX interrupt. Check source ID, enable, priority, claim and completion against the board implementation before reusing the RV32 PLIC fallback. Populate the device table with the devices this image supplies. [PLIC fallback](../hal/virt/plic.c) · [Existing device registration](../hal/virt/devices.c)

**First milestone acceptance.** Run the two-actor timer test and deliver two distinct UART bytes to a waiting actor in the same image. Verify both bytes, acknowledge the source and show scheduler progress afterward. A second delivery catches handlers that work once but leave the interrupt asserted or disabled.

**Storage follow-up.** Choose SPI microSD for standalone use or a rooted host service over UART for development. Give the chosen backend a QOS service interface and test readback, bounded requests and device errors. A UART-backed service also needs framing that can coexist with console traffic. Networking can follow when a transport has been chosen.

## 4. Run a separately loaded QOS application

Start service integration with a statically linked client. Then audit the process entry ABI, shared boot structures, word-sized tagged values, application linker layout, relocation handling and instruction-fetch synchronization after loading code. Verify what the RV32 loader supports before committing to an application image format. Budget process images and actor stacks against measured free SDRAM. [Shared boot ABI](../qos/native/shared_boot.h) · [Process entry](../qos/native/proc_entry.c) · [Current RV64 application layout](../qos/appside/link-qosapp-rv64.ld)

**Application gate.** Load a separately compiled RV32 app, complete a capability-checked service call, reject an unauthorized call, exit, then reload it. Record image size, free memory before and after each run, and successful service delivery after reload. This is the point at which to claim a usable native application port. The earlier board gates qualify boot, scheduling and device delivery individually.
