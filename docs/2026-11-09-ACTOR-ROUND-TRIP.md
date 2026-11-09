# Actor round trip against a syscall

Date: 2026-11-09. Kind: measurement, diagnosis and the first fix.

Goal, set by the owner: a message between two actors on QOS costs no more than
an actual syscall. This page measures both, breaks the round trip down, and
records step 1 of the plan: QOS Portable apps losing ~120 ns per round trip to
a compiler exception.

Baseline: QOS main `4e60743`, FP-RISC pin `e138e654` (`fprisc.lock.json`,
unchanged). The fixes are on fprisc branch `qosapp-receive-loops`: `3484418`
(receive-loop form) and `afcb0a0` (drain scan), on top of e138e65, not merged
or pushed. Host: Apple M4, macOS (Darwin 27.2).
Evidence: [evidence/2026-11-09-actor-round-trip/](evidence/2026-11-09-actor-round-trip/).
Related: [PORTABLE-MESSAGE-PASSING-TARGETS.md](2026-11-09-PORTABLE-MESSAGE-PASSING-TARGETS.md),
written the same day, calls the ~110 ns same-hart Portable-hosted gap
unexplained; section 4 explains it and section 5 closes it.

## 1. The bar: what a syscall costs here

`sysbench.c` (in the evidence directory; `cc -O2`), 2,000,000 calls each, three
runs:

| Operation | Cost |
|---|---:|
| null syscall (`getppid` through `syscall(2)`) | 75-98 ns |
| `write` of 1 byte to `/dev/null` | 720-815 ns |
| pipe ping-pong between two threads (one round trip) | 3,125 ns |

**The bar is the null syscall, ~80-100 ns.** A round trip (request and reply)
is compared against one syscall, because that is what an actor call replaces:
asking another part of the system to do something and getting the answer.

## 2. Where QOS was

`tests/ipcbench.fpr` (round trip = request plus reply) and two single-case
programs, `samehart.fpr` (tuple message, as ipcbench) and `intsend.fpr` (a bare
Int message), 20,000,000 round trips each:

| Runtime | Same hart | Same hart, Int message | Across harts |
|---|---:|---:|---:|
| hosted FP-RISC (`fpr build --harts 2`) | 170-177 ns | 121 ns | 370 ns |
| QOS Portable (`./qos.py run --harts 2`) | 305-363 ns | | 448 ns |

So Portable was 3-4x a syscall same-hart, and hosted 2x.

## 3. Where the time goes

### Hosted, same hart (177 ns)

`sample` on `samehart` built `--harts 1`, so every sample is on the round trip.
A round trip is two messages, two blocks and two context switches.

| Part | ns | Functions |
|---|---:|---|
| scheduler | ~63 | `block_unless` (seq_cst CAS and fence on every block and wake), `hart_loop`, `deq`, `backlog_add`, `wake`, `p_any`, `fpr_ctx_switch` |
| receive | ~28 | `a_receive`, `a_receive_from`, `take_at`, `fpr_rx_push`, `$receiveReady` |
| generic copy of a 2-field tuple | ~27 | `dc_dup`, `msg_copy_held_in`, `fpr_layout_fields`, `dc_release`, `fpr_alloc` |
| the program itself | ~18 | `$loop.in.ping`, `$loop.in.ponger` |
| send | ~16 | `fpr_send_as`, `ring_push`, `chan_for`, `inbox_reserve` |
| ARC | ~12 | `fpr_arc_incref`, `arc_slot_for`, `arc_decref_in` |
| turn and region boundary | ~11 | `g_region_cycle`, `transfer_copy_in`, `arena_reset`, `fpr_slabs_unhold` |

### QOS Portable, same hart (354 ns)

The app image has no symbols in `sample`'s output; addresses were mapped
against `.qos/build/qosapp-a64.elf` (`llvm-nm`), image base `0x10000000000`.

| Part | ns |
|---|---:|
| `dc_dup` + `dc_size_in` + `fpr_layout_fields` + `memcpy` | ~105 |
| `alloc_in_size` + `fpr_alloc` | ~51 |
| `hart_loop` + `block_unless` + `deq` + switch | ~75 |
| `fpr_apply` + `fpr_applyN` + `g_loop_in` | ~16 |
| the rest (receive, send, ARC, program) | ~107 |

Callers, from the call tree: all of `dc_size_in` comes from
`transfer_copy_in` under `g_loop_in`, the per-turn state copy of the
`$receiveLoop` trampoline. `alloc_in_size` comes from the turn functions
(`$receive.turn.ping`, `.ponger`) and from `fpr_applyN`, which is the
trampoline building and applying a closure per message.

## 4. Why Portable used the trampoline

On 2026-10-26 (fprisc `2201e4b`, docs/2026-10-26-RECEIVE-TURNS-PER-SLAB.md)
hosted receive loops moved from the `$receiveLoop` trampoline to the
loop-region form: direct tail calls, a region opened at entry, a cycle once a
slab fills. Pingpong went from 334-360 to 175-202 ms. QOS app images
(`oQosApp`: `qa64`, `qx64`, `qrv64`, `--system=qos-portable`) were excluded:
"their plane memory reclaims per turn through `$receiveLoop` ... the region
hooks do nothing in a plane process".

That reason does not apply to any image that flag selects:

- `fpr_plane_memory` is set in exactly one place,
  `qos/native/proc_entry.c`, the native kernel's process entry. QOS Portable
  apps (`qosp`) own their heap; their region hooks work.
- Native process images are built by `tools/build-process-app.sh` with
  `--target=rv64`, which does not set `oQosApp`. So they already took the
  loop form, and the exception never reached them.

The exception therefore only cost Portable apps the closure, apply and sized
state copy per message.

## 5. The fix and its effect

fprisc `qosapp-receive-loops`: `compiler/Compile.hs` passes
`receiveLoops = True` at both region-placement sites instead of
`not (oQosApp opts)`; comments in `Compile.hs` and
`Compiler/Native/Regions.hs` updated. `Regions.Options` keeps the field, which
`tests/RegionInterfaces.hs` uses to check the trampoline protocol directly.

QOS Portable, `./qos.py run tests/ipcbench.fpr --harts 2`, two runs each:

| Case | Before | After |
|---|---:|---:|
| same | 305-363 ns | 186-246 ns |
| same linear | 279-304 | 194-196 |
| same bounded | 305-315 | 199-219 |
| same 1k | 299-305 | 195-202 |
| cross | 448 | 360-440 |
| cross bounded | 499 | 378-470 |
| relay 16k copy (three hops) | 1,273-1,288 | 972-1,012 |
| relay 16k move (three hops) | 766-779 | 453-494 |

`samehart` under QOS, `--harts 1`: 354 -> 185 ns. Its profile now matches the
hosted one: no `dc_size_in`, no `alloc_in_size`, no `fpr_applyN`.

Quiet re-runs later the same day (three each, back to back, see section 6)
put the fix alone at 174-178 ns same hart and 329-346 ns cross hart: the
186-246 spread above came from a busier machine.

**Full check-all with fprisc `3484418`** (qos `4e60743`): 145 passed, 9 failed,
9 skipped, against 146/8/9 for the 6 November pin trial (e138e65, qos
`03ccd4a`). The one new failure is `versions`: `fpr.lock` on qos main lacks the
three pins `tests/epbench.fpr` added (`epservice`, `ep`, `std/actor`), which is
independent of the compiler (the check reads only qos's pins and store). The
other eight failures are the same legs as on 6 November. The memory-retention
legs (Memory.qa, mailbox, ARC audit, preferences, storage, app memory) all
pass.
`legs-3484418-qos4e60743.tsv` in the evidence directory.

## 6. What is left, and the plan

Same hart, after the receive-loop fix, Portable was ~175 ns: about 2x the bar. In order:

1. **Cross-hart ring scan (~10 ns, small).** `drain` (runtime/actors.c)
   scans `FPR_NHARTS` incoming rings on every scheduler pass. An app image is
   built for 8 harts and usually runs 1-4, so the profile shows the 8-way
   scan in `hart_loop`. Bound it by `fpr_live_harts`, as `hart_quiet` and the
   other per-hart loops already do. **Done** (`afcb0a0`). Three runs each,
   back to back:

   | Case | Without | With |
   |---|---:|---:|
   | same | 174-178 ns | 168-171 ns |
   | same linear | 175-178 | 167-173 |
   | same bounded | 196-200 | 188-193 |
   | same 1k | 193-195 | 180-185 |
   | cross | 329-346 | 325-337 |

   About 6-8 ns same hart; cross hart within noise. QOS Portable same hart is
   now at or below the hosted runtime (170-177 ns).
2. **Direct handoff (~40 ns).** When an actor sends to an actor on its own
   hart that is blocked waiting for it, and then waits for the reply, switch
   to it directly: no run queue, no `hart_loop` pass, no backlog. This is
   the call path L4-family kernels use. The zero-overhead proposal lists
   direct handoff as deferred; this measurement argues for moving it up.
3. **Small-message fast path (~30-40 ns).** A message of a few words (ints,
   actor handles) copied straight into the ring slot, without the generic
   copier, a slab, or ARC. The Int case is 56 ns cheaper per round trip than
   the 2-tuple case today.
4. **Inline bump allocation for QOS apps.** fprisc
   docs/2026-11-03-INLINE-BUMP-ALLOC.md still lists loaded QOS apps as not
   qualified. It no longer shows in this benchmark after the fix, but apps
   that allocate per message still pay a call per allocation.

Estimated floor after 1-3: about 50-70 ns per same-hart round trip, under the
bar. That is an estimate from the breakdown, not a measurement.

**Cross-hart cannot meet the bar on this hardware.** A round trip moves at
least two cache lines between cores each way, and waking a sleeping hart is
itself a syscall (a condition-variable signal). With the actor block spin on
(qos docs/2026-11-07-PORTABLE-BLOCK-SPIN.md), ~150-200 ns is a realistic
floor; today's 360-440 ns is about 4x the bar. Cross-hart is already 7-8x
cheaper than the kernel alternative measured above (pipe ping-pong,
3,125 ns).

## 7. Limits of this evidence

- One machine (M4, macOS), runs repeated at most twice; the cross-hart
  figures vary by about 20% between runs.
- Not measured: the QOS native kernel (RISC-V, QEMU) and the Pi 4B. The Pi's
  syscall cost is different and the bar should be measured there too.
- The breakdowns are sampling profiles (`sample`, 1 ms), so parts under
  ~2 ns are noise.
- The native plane question in section 4 was settled from the build scripts
  and the one assignment of `fpr_plane_memory`, not by running a plane image
  before and after.
