# FP-RISC pin trial: e56633af (round-trip runtime on main)

Date: 2026-11-12. Kind: pin trial, tested. Branch `fprisc-pin-rt` on main
`0e2cdb9` plus `actor-round-trip-note`. Verdict: **go** for QOS, with one
FP-RISC main regression to report (liveboard, hosted only).

## The pairing

FP-RISC `e56633af` is branch `qosapp-receive-loops` (20ad433, deployed to the
Pi on 10 November, never merged) rebased onto FP-RISC main `4740d788`, branch
`qosapp-receive-loops-main`:

| Commit | What |
| --- | --- |
| 7d17bd69 | QOS app images take the receive-loop form |
| 2d1f100b | the scheduler drain scans only live harts' rings |
| 40147332 | direct handoff on a same-hart call |
| 72ef1d68 | small flat messages carried in their ring slot |
| 8b560492 | bounded inboxes on the slot-carried path |
| e56633af | codegenRev 215 |

Rebase conflicts and what was done:

- `Regions.Options` gained `persistentLoop` on main (automatic copy-out);
  kept, with `receiveLoops = True` everywhere as the branch intended. QOS
  app targets keep copy-out off (`persistentLoop = Nothing`), as on main.
- The actor context moved into the live block on main (`live_block(a)->ctx`);
  `direct_handoff` switches `live_block(a)->ctx -> live_block(b)->ctx`.
- Fuel is a register on main (x27/s11, `fpr_fuel_set`); `resumed()` refills
  with `fpr_fuel_set` instead of writing the old memory cell, so a handoff
  refills the counter the generated code reads.

Against main, the pin also brings everything FP-RISC main gained since
`e138e65`: register fuel and weighted ticks (#67, #68), the actor-death and
hart block-cache fixes (#69, #70), typed lowering, copy-out and static
reuse for hosted programs.

## QOS changes that come with it

- `fprisc.lock.json` -> `e56633afc4669797d7d5914bb1303439bd32ed5a`.
- **`-ffixed-x27` on every RISC-V C compile** that links generated code: the
  native kernel (`qos/Makefile` `ARCHFLAGS`), RV64 app images
  (`qos-app.mk`), process images (`tools/build-process-app.sh`, RV32 and
  RV64) and the checks that build their own kernels (`block-ownership`,
  `failure-injections`, `native-abis`, `native-integrity`, `net-policy`).
  Generated RISC-V code keeps fuel in s11; C that uses s11 as a callee-saved
  register would restore its own value over a refill. A64 builds already
  passed `-ffixed-x27`.
- `appside/entry.c` keeps writing `hi->fuel` for secondary harts and says
  why: on A64 and RISC-V the counter is a per-thread register the trampoline
  refills; `fpr_fuel_set(hi, ...)` would write the calling thread's register.
- `tests/arcaudit.fpr` (from `actor-round-trip-note`, 35f4d39): its leaked
  pair is nested, because a flat `(Int, Int)` now rides in the slot and is
  not ARC-counted.

## Results

`check-all.sh` with `FPRISC_ROOT` = the rebased checkout: **145 passed,
9 failed, 9 skipped** of 163 legs (75 min), the same totals as the
`20ad433` sweep of 10 November.

| Leg | 10 Nov (20ad433) | Now | Why |
| --- | --- | --- | --- |
| Native instruction ratchet | fail | pass | ceilings 474/95 on main (e1ce71e) |
| versions (fpr.lock) | fail | pass | epbench pins on main (79d84e3) |
| failure honesty | pass | fail | FP-RISC main: Sol's message for an unsafe import changed (`M.loop is unsafe (recursive)` where the check expects `main is unsafe`); fails identically with a build of plain main `69d893a0` |
| liveboard (std/live) | pass | fail | FP-RISC main: the hosted liveboard server segfaults under 100 websocket clients, `dc_size_in` <- `transfer_copy_in` <- `g_region_cycle` in `$loop.cycle.broadcast` (NULL+8); a build of plain main `69d893a0` crashes with the same stack. Automatic copy-out landed on main on 11 November. QOS apps have copy-out off. |
| dedup ratchet, Graphics.qa, toolchain, Sol NN, Vec fusion, Vec fixpoint, sol Ok/Err | fail | fail | the standing every-pin failures |

Also, before the sweep:

- A runtime differential, FP-RISC main's runtime against the rebased one
  (same compiler, `FPR_HOME` switched), every `tests/base` and `tests/edge`
  program at 2 and 4 harts: 620 runs, no program's result differs.
- FP-RISC `tests/check_spawn_scaling.py` and `tests/check_tick_batch.py` pass.
- `tests/ipcbench.fpr` on Portable runs with register fuel (smoke).

## Measured

QOS Portable, M4, release build of each arm, `tests/epbench.fpr` (one hart)
and `tests/ipcbench.fpr` (two harts), the host `tests/epbench_syscall.c`
(one-word write to `/dev/null`) after each pair. Five interleaved rounds,
baseline = QOS `7992992` (main + Qlog v11, which neither bench touches) with
FP-RISC `e138e65`; pin = this branch with `e56633af`
([raw](evidence/2026-11-12-pin-e56633af-ipc.txt)). The machine was busier
than on 11 November (host write 828-1,224 ns, against 673-678 ns in a quiet
pin-only run just before), so compare columns, not absolutes:

| ns | e138e65 | e56633af |
| --- | ---: | ---: |
| Same-hart round trip | 343-412 | 121-153 |
| Cross-hart round trip | 730-895 | 432-582 |
| Held endpoint write | 523-841 | 344-554 |
| Open, write, close | 2,853-3,494 | 1,987-2,196 |
| Host `/dev/null` write | 828-1,224 (same runs) | |

A quiet pin-only run of five rounds just before (both arms of that run were
accidentally the pin build) gave same hart 105-108 ns, cross hart 219-248 ns,
held write 347-379 ns, open-write-close 1,553-1,645 ns, host write
673-678 ns. **A held endpoint write now costs about 0.53x a one-word
`/dev/null` write** (it was 0.7-0.9x on 11 November at `e138e65`), and the
round trip is at the null-syscall level (75-98 ns, 9 November).

## Left

- Push `qosapp-receive-loops-main` and open its FP-RISC PR (not done from
  this session); QOS CI fetches the pinned revision from GitHub. Rebasing it
  onto `69d893a0` (one commit, static reuse increment 6) changes the hash
  and needs a smaller re-check.
- The liveboard crash and the failure-honesty message belong to FP-RISC main.
- The Pi 4B and the native board were not re-run at this pin.
