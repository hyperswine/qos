# Pipeline progress and cache footprint of the linked chooseRight call

The measured object is the complete counter-read window of the parent stress
probe. All comparisons use that same window. The frozen observed core and
four-clock cache are simulation models of the 54 MHz Spectre design. The
board has the qualified ROM-patched bitstream; equivalence of the observed
model to the deployed gate netlist remains open.

## Progress and placement

At slot 1 base 0x800d1980 the opening and closing cycle reads are at offsets
0xb0 and 0xc0. The call and its inner instret reads share those two 16-byte
lines. chooseRight occupies four lines at offsets 0x1a0–0x1d0 inclusive. Its
two aligned stack words share one more line. Thus the architectural footprint
is seven lines. Fetch-ahead, stale predicted targets and carry-in writes
also reach the cache port. The native executable and its return value are
unchanged. A simulation boot shim installs the linked job at the same base,
selects the initial stack and substitutes a returning console callback; this
changes the call history compared to the QOS serial driver.

The monitor brackets the successful read phase of the two mcycle CSRs. It
counts physical clocks, clocks on which the cache lets the CPU advance, and
the maximum advancing-clock gap between changes of architectural minstret.
It includes partial gaps at the two boundaries and checks 14 retirements
across the outer window and 12 between the nested minstret reads.
All 25,600 simulated windows had a maximum gap at or below 14, versus the
proposed limit of 32. Lowering the assertion to 10 failed on the first
window. There were 68 observed CSR carry-retry clocks across the sweep.

Five aligned stack placements include set aliases with the wrapper, leaf and
injected targets. Each uses 256 iterations through the four board stress
modes. There are ten predictor/counter configurations and two tag settings.
The ordinary configuration trains from reset. Nine injected configurations
sweep all 256 BTB validity masks for each of three tag assignments and three
target families (off-path SDRAM, self/upper-halfword, and chained aliases).
They vary both low counter words near rollover. The tag perturbation clears
both ways at the sample boundary, suppresses stale lookup hits and retains
posted writes. These are deliberately seeded RTL states. The bench uses
the actual historical burst/refresh state machines, with RAM data supplied
by a testbench array. It uses nominal digital timing.

## Cycle accounting

The analysis consumes the cache A2 address on advancing edges, including
speculative SDRAM reads and carry-in writes. It starts with no known resident
line. For each set it remembers at most one line: a read to another tag
charges a refill, and every store forgets the resident line in that set.
This intentionally discards the second way and the benefit of write hits.
The cache freezes a missed request until refill, then forwards the filled
line. Repeated reads can therefore share a fill. A set conflict or store
can cause the same line to be charged again. The analysis checks the charge
against accepted RTL refills for every trace. It retains the parent model's
20-clock transaction allowance, charges every write pushed during the window,
four possible queued writes at entry, and one extra carry-in transaction.

For each trace calculate advancing clocks + 20 × (charged fills + pushes + 5).
Take the maximum of the resulting per-trace ceilings. Independent column
maxima need not occur on the same trace.

| Quantity | Ordinary training, unmodified tags | Full stress sweep |
|---|---:|---:|
| Windows | 1,280 | 25,600 |
| Max advancing clocks over whole window | 81 | 111 |
| Max advancing clocks between retirements/boundaries | 14 | 14 |
| Max distinct SDRAM lines read | 9 | 22 |
| Max distinct SDRAM lines touched, including stores | 9 | 23 |
| Max actual accepted refills | 7 | 22 |
| Max charged fills | 10 | 24 |
| Max total charged transactions | 18 | 32 |
| Max physical clocks in simulation | 163 | 360 |
| Max per-trace cycle ceiling | 422 | 751 |

The earlier ceiling was 9,648 cycles. Keeping its 32-clock progress premise
but using the tested transaction envelope alone gives 14 × 32 + 20 × 32 =
1,088 cycles. Using each replay's actual advancing clocks brings the envelope
to 751 cycles (13.91 us at 54 MHz). The fresh physical run had 2,160 successful
calls, 12 inner retirements each, 163 cycles on first invocation and a maximum
of 139 in combined conflict/write stress. Against the overall physical
maximum the old ceiling was 59.2× and the full replay envelope is 4.61×.
The ordinary replay ceiling is 2.59×. The 360-cycle simulated window is
evidence that board sampling alone misses slower modeled states.

These are finite, trace-conditioned results. The validity masks are exhaustive
within each supplied assignment; arbitrary BTB tags, targets, stack layouts,
queue contents and all legal prehistories are not enumerated. The progress
test covers this interval and its boundary fragments, not every instruction
or whole actor turn. For a deployable bound, establish a reachable-entry
invariant (or explicitly clear/constrain predictor state), then model-check
retirement progress and transaction counts under that invariant against the
qualified core. In particular a seven-line allowance cannot account for stale
predictions even on this tiny function.

## Reproduction

Set QOS, FPRISC and SIMPLE_RISC to their checkouts and SPECTRE_IMAGE to the built
hal/spectre/tools/spectre-image, and run `sol run.sol NEW_OUTPUT_DIRECTORY`
(the analysis step takes about two minutes in Sol). The script rebuilds and verifies the exact
guest payload and pins all simulation HDL hashes. The generated per-window
port traces are under runs/. The fresh UART transcript is physical.log.
The negative control is `obj_dir/Vtb +limit=1 +cap=10` from the output
directory; it should fail with gap 14. The RTL perturbation uses private
fields of the pinned simulation model.
