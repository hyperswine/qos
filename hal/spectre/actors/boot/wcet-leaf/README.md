# First Spectre FP-RISC leaf timing probe

The qualified 54 MHz Tang Nano ran this separately linked SXA2 probe in QOS job
slot 1. The function is the compiler-emitted RV32 Builtin chooseRight from
leaf.fpr. Its second argument varies from 1 through 31 in steps of two.
The driver calls the symbol through a register to prevent constant folding.
It saves and restores the machine interrupt-enable bit around each short
sample, prints counters afterward, and exits 42 only after all comparisons.
This bounded entry deliberately omits the application builder's optional
measurement-external work and its normal inserted actor polls. Do not use
the fixture builder for general unbounded apps.

## Exact linked bound

At image offset 0x138 the function has five register instructions, two word
stores, two word loads and a return, with one path and no calls. Given a valid
aligned actor stack and return address, all tagged inputs retire exactly ten
instructions. From the first minstret sample to the second, the opening CSR
instruction and indirect call add two. The empty function consists of ret, so
its corresponding count is three. The board matched 12 and 3 on all 16 pairs.
The enclosing mcycle interval includes both minstret reads. Its 14 instruction
steps from the opening cycle read to the closing cycle read comprise five
register ops, two stores, two loads, two indirect transfers and three CSR steps.
The two boundaries of the same kind allow read-to-read accounting.

| Raw interval | First pair, cycles | Subsequent 15 pairs, cycles | Retirements |
|---|---:|---:|---:|
| Empty call returning immediately | 104 | 62 | 3 |
| Call to chooseRight | 128 | 81 | 12 |

At nominal clock the raw leaf-call interval ranged from 1.50 to 2.37 us.
Pairwise differences were 24 then 19 cycles. The empty call goes to another
address and its ret is also timed. Subtraction is an incremental comparison,
not an upper bound on isolated function execution. Cache state was not forced
or recorded. The first sample is the first invocation, not a verified
all-cache-cold state. Low-word unsigned deltas are valid modulo 2^32 here
for intervals shorter than one counter wrap (about 79.5 seconds at 54 MHz).

## Physical-cycle bound still to discharge

A path-specific conditional budget for the raw interval is
**5A + 2S + 2L + 2J + 3C** cycles. Each coefficient comes from linked.txt.
A, S, L, J and C must bound progress for a register step, aligned stack store,
aligned stack load, indirect transfer and counter step in every admitted
pipeline state, with fetch included. Charge each inter-retirement interval
once. For a CSR read-to-read window include boundary phase costs in C or add
an explicit boundary allowance. The leaf alone has budget 5A + 2S + 2L + J
at instruction retirement boundaries. The raw measurements constrain the
model: any claimed cap below 128 for this raw window already has a physical
counterexample. They do not prove that 128 is sufficient.

The pinned top uses the two-way pipeline cache, a four-entry write queue and
the single-clock burst SDRAM controller. Establish progress bounds for
refill, same-line queued stores, queue-full stalls and refresh, plus pipeline
redirects, hazards and split-counter carry. Include speculative fetches.
A next test is to force conflicting lines and vary refresh phase, compare
RTL cycle traces to hardware, and refuse a numerical WCET until the timing
model covers those states. This interval excludes scheduler and UART latency.

## Reproduce

With the installed qualified QOS kernel and the Simple-Risc UART tools, copy
this directory to a writable build directory and run:

    sol "$QOS"/hal/spectre/actors/boot/wcet-leaf/build.sol "$FPRISC/fpr" "$QOS/hal/spectre/actors/boot/apps"    # SPECTRE_IMAGE names the built spectre-image
    riscv64-unknown-elf-objdump -d leaf.elf > linked.txt
    sol "$QOS"/hal/spectre/actors/boot/wcet-leaf/board.sol > board.log
    sol "$QOS"/hal/spectre/actors/boot/wcet-leaf/analyse.sol

board.sol warm-resets the CPU, verifies the SD boot marker, creates a
content-named probe file or verifies the existing one, then runs it and checks
the exit status. The archived run used FP-RISC 18fce327 (compiler SHA-256
7d0183774b137c5645a5d296d90ce4597b70a34685e8b92095e5c4bce8ef07f2),
runtime 566870c3, QOS qualified by 20ccd23 (kernel SHA-256
43c39ae149da28cd7e8276fc6b7482110cc20d719f8ea9bcb158178fa56fe9e2), and
Spectre btbdef-54 (FPGA SHA-256
7782fd5d8a751ed90e70f35764b63ff86efeb1f155dc398cc4add2c266ebaa26).
These deployment identities come from the qualified build record. The UART
check observes SD boot, verifies the app bytes by name and launches slot 1.
See result.json for the exact ELF and package hashes and board.log for each
sample. The console is back at the prompt.
