# VERIFICATION.md — verifying the C under QOS (a study, with three probes)

The question: the whole language side is checked by types, linearity,
proofs (`std`) and transactions, but the floor under it is ~11k lines of C
(the HAL runtime, the portable host) that is tested only by example legs
in `check-all.sh`.  What would it take to verify it better -- property
tests, bounded model checking, model checking of protocols, deductive
proof -- and does restricting HOW we use C make that cheaper?  This page
is the survey plus three probes that actually ran; `qos/tests-host/verify/`
is the runnable slice.

## 1. What the C actually is

| tree | lines | what | verification-relevant traits |
| --- | --- | --- | --- |
| `runtime/runtime.c` | 2162 | allocator (per-actor pools, buckets, bigfree), generic apply, core prims, panic | 20 atomics, 6 unions, 5 inline asm, 30 named panics |
| `runtime/actors.c` | 1456 | multi-hart actor runtime: ACBs, per-sender SPSC channels, epoch limbo, wake/IPI, fuel | **63 atomics**, 13 volatile, 35 named panics -- the concurrency core |
| `runtime/vec.c` | 760 | linear SoA vectors, SIMD zips, compaction | pure loops over columns, 24 panics |
| `runtime/buddy.c` | 284 | power-of-two buddy over a reserved arena (alloc / realloc / free) | sequential under one lock; the cleanest target |
| `loader/process.c`, `elfload.c`, `qaimg.c`, `apps.c`, `mod.c`, `sstr.c`, `bits.c` | ~900 | loading, image parsing, module table, small strings | parsers with explicit bounds checks; `qaimg.c` is a 103-line pure parser |
| `hal/virt/*` | ~1200 | bare-metal: CLINT/PLIC, blk/net virtio, context switch (`.S`) | MMIO through `volatile`, 2 inline asm files -- model, don't prove |
| `hal/unix/*`, `qos/portable/*` | ~3000 | the Linux host: tty/evdev/drm/net raw shims, gfx, hostlog, the qosp loader and QAR2 reader with SHA-256 | libc + pthreads; `qa.c` (275 lines) is another pure parser |

Things that make it easier than "generic C": no recursion to speak of, no
`setjmp`, no varargs outside the log sink, no function-pointer tables
except the HAL table and scheduler plane, fixed-size arenas and rings,
every invariant already spelled as a `fpr_cpanic` (120+ of them), and
every subsystem documented as laws (`docs/MEMORY.md` "The laws", the
allocator contract; `docs/QA-FORMAT.md` "the entire loader contract, as
text").  Things that make it harder: 63 atomics with explicit
acquire/release in `actors.c`, epoch-based reclamation (`chblk` limbo),
and MMIO.

## 2. The options, honestly

| approach | what it proves | where it fits here | cost | verdict |
| --- | --- | --- | --- | --- |
| **Property-based testing** (Hypothesis via ctypes, or `theft` in C) | invariants hold on thousands of random op sequences, with shrinking to a minimal counterexample | every sequential module: buddy, pools/bigfree, vec compaction, sstr, the two parsers, QLOG record layout | hours per module; runs in seconds | **do first** -- it is what the existing `tests-host/*_check.c` legs are, minus the randomness and shrinking |
| **Bounded model checking** (CBMC) | ALL paths up to a bound, incl. pointer/bounds/overflow checks, for real C | the same sequential modules, small bounds | minutes to hours of SAT per harness; blows up fast (see §4) | **do second**, on parsers and buddy, opt-in in the sweep |
| **Fuzzing** (libFuzzer/AFL with sanitizers) | crash-freedom on adversarial bytes | `qaimg.c`, `qa.c` + SHA, QLOG readers, the wire JSON of `Web.hs`'s peer | cheap; needs a fuzz target per parser | do for the parsers; complements PBT |
| **Model checking a MODEL** (SPIN/Promela, TLA+) | the protocol is right: no lost/duplicated/reordered messages, no deadlock, bounds respected, liveness under fairness | the SPSC channel, wake/IPI handshake (Dekker fence), epoch limbo reclamation, the scheduler plane, the transaction lock/validate/commit protocol in Sol's `Txn.hs`, QLOG's two-boot recovery | days per protocol; the model is hand-written, so its fidelity to the C is the risk | **do for actors.c's three protocols** -- nothing else can reason about the atomics |
| **Deductive proof of C** (Frama-C/ACSL + WP, VST) | full functional correctness of functions against contracts, unbounded | buddy, vec loops, parsers | weeks per module; needs a C subset (no unions-as-casts, loop invariants everywhere) | later, only for buddy and the loaders, if ever |
| **Isabelle / Coq** | anything, incl. the language's semantics (linearity, the drop law, transaction atomicity) | the LANGUAGE, not the C: prove the type system's laws once | months | the right tool for "linearity implies no leak"; wrong for `actors.c` |
| **Maude** (rewriting logic) | executable semantics + search | the transaction model or the actor semantics as rewrite rules | weeks | overlaps SPIN/TLA+ with better fit for semantics; niche |
| **seL4-style full stack** | everything | -- | years | no |

The pattern: sequential data structures get PBT now and CBMC when a
harness is small; concurrent protocols get a SPIN model; the language's
laws get a proof assistant if and when the semantics are written down
formally.  None of these replace the example legs -- they make the legs'
claims quantified ("300 random sequences", "every path to depth 8",
"every interleaving of 2 processes with a 4-slot ring").

## 3. A subset of C worth writing down

Enumerating how the backend uses C is cheap and pays twice: it is the
input a Frama-C/CBMC harness needs, and it is a review checklist.  What
the code already does, made explicit as "QOS C":

1. **Memory comes from arenas, never `malloc`** (the host shims and gfx
   are the exception, and they are host-only).  Every block has a
   header word; sizes are powers of two or exact-fit from a freelist.
2. **No recursion.**  Every loop is bounded by a size that is a
   parameter or a constant; that bound is the CBMC unwind.
3. **Concurrency is atomics + one lock per owner**, never data races on
   plain fields: every shared field is read with `__atomic_load_n` and
   written with `__atomic_store_n`, with the release/acquire pairs
   named in a comment (they are, in `actors.c`).  Lock-free structures
   are SPSC or CAS-claimed only.  This is what a Promela model can be
   checked against mechanically (each atomic is one model step).
4. **Every invariant is a `fpr_cpanic`**, not a comment.  Those panics
   are exactly the assertions PBT and CBMC check; a new invariant
   without a panic is untestable.
5. **Parsers take (pointer, length) and never read past `end`**; every
   number parsed is bounds-checked before use (`qaimg.c` is the
   template).  These are the fuzz targets.
6. **No unions for type punning outside `fpr.h`'s value representation**;
   no `setjmp`; no variadics outside the log sink; function pointers
   only in the HAL table and the scheduler plane.
7. **MMIO only through `hal/virt`'s `volatile` accessors**, so the
   `hal/core` layer is host-testable without hardware.

A clang-tidy or a 40-line script can enforce 1, 2, 6 and 7 mechanically
(grep for `malloc`, recursion via the call graph, `union`, `setjmp`,
`va_`, `volatile` outside `hal/virt`).  3 and 4 are review rules; 5 is a
harness per parser.

## 4. Three probes that ran (qos/tests-host/verify/)

**Property-based: buddy.c through ctypes with Hypothesis** (`pbt_buddy.py`).
The real `buddy.c` compiled as a shared object with `FPR_BUDDY_MIN=64`; a
stateful test draws alloc/realloc/free sequences and checks after every
step: blocks inside the arena, usable size covers the request, live
blocks (headers included) never overlap, every payload byte-pattern
intact across realloc, free bytes plus live bytes never exceed the
arena, and freeing everything restores the initial free count exactly.
300 sequences of up to 60 steps: 5.7 s, all invariants held.  A
counterexample would be shrunk to the shortest failing sequence.  This
is the existing `buddy_check.c` stress leg with generation and shrinking
done by a tool instead of `rand()`.

**Bounded model checking: buddy.c under CBMC** (`buddy_cbmc.c`).  One
nondeterministic alloc/free cycle over a 4-block arena with CBMC's
bounds and pointer checks and the contract as assertions: VERIFICATION
SUCCESSFUL, 9 properties, 4 min 50 s (289 s in the SAT solver).  Scaling
is the honest finding: three allocations with a nondeterministic free
order and `--pointer-check` produced 6 000 to 90 000 verification
conditions and was killed at 16 GB.  Per-loop `--unwindset` is essential
(`buddy_init`'s 26-iteration loop), pointer checks multiply the cost, and
the useful targets are the parsers (`qaimg.c`, `qa.c`) and single
operations, not whole sessions -- PBT covers the sessions.

**Model checking a protocol: the SPSC channel under SPIN** (`spsc.pml`).
`chan_t` as a Promela model: free-running head/tail, the producer's
private `rt` published after the slot write, the consumer's acquire load,
a 4-slot ring, 6 messages.  Verified: the consumer never reads an
unwritten slot, FIFO order, `[] (rt - rh) <= CAP`, and `<> (recv == N)`
under weak fairness -- errors 0, 93 states deep.  Trivial as a model, but
it is the template for the two protocols that matter and that nothing
else can check: the wake/IPI Dekker handshake (`fence; wake(a)` against
`block_unless`) and the `chblk` epoch limbo (a reclaimed channel block is
reused only after every hart has advanced two epochs).  Those models are
a few dozen lines each; their value is in the counterexample trail when
someone touches `actors.c`.

`verify.sh` runs the PBT and SPIN parts in seconds (skipping any tool
that is absent) and the CBMC part only with `VERIFY_CBMC=1`.  It is a
check-all leg.

## 5. Recommended path

1. **Now, cheap:** PBT harnesses for the sequential modules in the order
   of blast radius -- buddy (done), the per-actor pool and bigfree
   (`runtime.c`), `vec.c` compaction and the SIMD zips against a
   reference in Python, `sstr.c`, and the two parsers with adversarial
   bytes.  Each is a Python file next to the existing `*_check.c`.
2. **Next:** SPIN models of the wake/IPI handshake and the epoch limbo,
   plus the Sol transaction protocol (lock order, validate, journal,
   replay, recovery after a crash at any effect index -- `SOL_CRASH_AT`
   already exists as the test hook).  These are the properties whose
   failures are the ones we cannot reproduce by running programs.
3. **Then, selectively:** CBMC on `qaimg.c` and `qa.c` with adversarial
   images (small bounds, pointer checks on), and on `buddy_realloc`'s
   in-place/copy decision.
4. **Write the subset down** as `docs/QOS-C.md` (the seven rules above)
   and enforce the mechanical ones in the sweep.
5. **Proof assistants** only for the language laws, when the semantics
   are written formally; not for the C.
