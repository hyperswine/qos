# Spectre chooseRight timing under memory pressure

This is a **conditional engineering ceiling** for the qualified 54 MHz
single-hart SD image. The board experiment measures one application in job
slot 1 with machine interrupts masked across each sample. It checks the
return value on every call. The leaf instructions are bit-for-bit the same
as the earlier leaf fixture; the enlarged driver puts them at offset 0x1ac.

## Counting physical clocks

Use the historical four-logical-clock cache port for btbdef-54. The later
three-clock implementation in the current Simple-Risc checkout changes the
latency. The existing-54 build script and netlist identify the two-way,
11-index-bit pipeline cache and the single-clock 54 MHz burst controller.
The archived October 30 baseline sources supply the behavioral model. The
physical run uses the previously qualified ROM-patched FPGA and SD kernel
identified in the parent experiment. A gate-level equivalence proof between
that archive and the deployed FPGA is outstanding.

Split the cost into advancing pipeline clocks and extra held clocks. For the
aligned, ten-instruction leaf and the enclosing 14-step cycle-read window,
use the following assumptions and charges.

* **Core progress assumption, 32 advancing clocks per step.** Serialize the
  in-order work, allowing two ten-clock fetch-to-commit traversals (four
  fetch-port clocks and six front-end/execute/commit stage transitions each)
  for a restart or failed prediction. Allow three further clocks for the
  historical external load wait, then nine for data hazard resolution,
  handover, CSR read/write, carry retry and counter boundary phase. Word
  stores, the register operations and both JALRs have no divide, unaligned
  assist or device wait. Interrupts, faults, reset and scheduler entry are
  excluded; the stack must be valid SDRAM. This is a conservative progress
  contract inferred from the pipeline structure. It still needs a
  reachability check for all admitted predictor, dependency and counter-carry
  states. The cache simulation below does not establish this CPU contract.
* **One physical transaction, 20 clocks.** In burst_memory and sdram,
  an accepted write clears busy at T_RCD+T_WR+T_RP = 4. A four-beat read
  clears it at T_RCD+CAS+3 = 6. A due refresh takes T_RC = 4 and resets the
  refresh timer at issue. Budget six clocks for the longer transfer, six for
  refresh including admission edges, and eight for arbitration, registered
  busy/done, cache FSM transitions and resumption. The interval between
  refresh requests is at least 540 clocks, so a single waiting transaction
  cannot be repeatedly displaced by refresh under this budget. This charge
  assumes an initialized single-clock controller with no competing master.
* **Transaction multiplicity.** The unified CPU port can present at most one
  new request per advancing clock; a held request is frozen until its miss
  is resolved. Charging every advance as a separate four-word miss covers
  incorrect-path fetches and load requests too. Add one carry-in miss.
  A held miss can drain pending same-line writes before the refill. Charge
  writes separately over the whole interval: four queue slots at entry,
  four conservative carry-in slots for the registered request/lookup path,
  two stores in the leaf and one extra in-flight transaction. This
  deliberately permits double counting. No additional stores issue from
  speculative instructions before commit.

For N steps, A = 32N and the physical ceiling is A + 20(A + 1 + 11).
The body-only retirement budget is **6,960 cycles**. For the raw cycle-read
interval, including the indirect call and counter work, the ceiling is
**9,648 cycles** (178.67 microseconds). Use the latter for comparisons to the
board. Both ceilings depend on the core progress assumption. The deliberately
loose part is charging a miss on every advancing clock, including clocks
when the core is waiting or fetching instructions within an already-filled
line. Neither value is a deployment-qualified hard deadline.

## Board observations

Each row represents 540 trials, interleaved by mode. Delay iterations vary
from 0 through 539 independently of the mode. On a two-way cache, flipping
byte-address bits 15 and 16 gives different SDRAM tags for the same set.
Conflict preparation reads two aliases for each of three code lines and
for the stack line used by the leaf. It does not evict every possible
instruction fetch. The posted-write stimulus issues four consecutive stores,
the last to the forthcoming return-address location, just before the opening
cycle read. Queue occupancy at that read is not externally observable.

| Preparation | Physical cycles | Retired instructions |
|---|---:|---:|
| Baseline | 81 (539 times), 163 (first invocation) | 12 |
| Conflict reads | 133–138 | 12 |
| Four stores | 81 | 12 |
| Both | 134–139 | 12 |

The largest raw observation, 163 cycles (3.02 us), is 1.69 percent of the
window ceiling, about 59.2 times smaller. The largest combined-stress sample
was 139 cycles. SDRAM refresh remained active throughout. Start-cycle residues
cover 340–350 distinct low-word residues modulo 540 per mode. These residues
are a sampling diagnostic; refresh may defer and its issue resets its private
timer, so this is not a board refresh-event trace.

## Cache/refresh evidence and reproduction

The cycle-level Icarus bench drives the archived cache, burst adapter and real
controller state machines after initialization. For each starting refresh
count 0..539 it issues four same-line writes followed by a miss and checks
queue occupancy and maximum hold. All 540 cases reached four pending writes;
40 had a directly observed refresh issue during the hold. The longest hold
was 44 clocks. The bench covers a single request pattern; the SDRAM data
pins are unmodeled because this test checks controller timing.

From a writable copy of this directory with SIMPLE_RISC, QOS and FPRISC set:

    cp "$QOS"/hal/spectre/actors/boot/wcet-leaf/leaf.fpr .
    sol "$QOS"/hal/spectre/actors/boot/wcet-leaf/build.sol "$FPRISC/fpr" "$QOS/hal/spectre/actors/boot/apps"
    riscv64-unknown-elf-objdump -d leaf.elf >linked.txt
    sol "$QOS"/hal/spectre/actors/boot/wcet-leaf/stress/board.sol >board.log
    sol "$QOS"/hal/spectre/actors/boot/wcet-leaf/stress/summary.sol
    sol "$QOS"/hal/spectre/actors/boot/wcet-leaf/stress/run-rtl.sol

The board harness warm-resets to the SD bootloader, verifies the stored app by
name, checks all 2,160 counts and requires the successful exit. The raw cycle
and retirement differences use 32-bit modular subtraction over short intervals.
The probe package SHA-256 is
5cc9755b1814caf3427556ffa5ac828138cd801060b3b289a687e7c0ba31e86f.
