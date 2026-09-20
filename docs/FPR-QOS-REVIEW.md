DESIGN & CODE REVIEW · 2026-08-29 · REPO @ 614A9E9
The qos-fpr Review
FP-RISC, Sol, and QOS measured against their own ethos — simple elegant code over premature optimization; linear vectors, refcounting, lambda lifting; no closures, no GC — plus an honest read on day-one usability and Linux-appliance readiness.

~57k lines reviewed: 18.8k Haskell · 12k C · 21k .fpr · 4.6k .sol. Four deep passes (compiler core, Sol pipeline, QOS/HAL, language-as-used); top findings re-verified against source by hand.

FP-RISC COMPILER
Strong core, fraying seams
Frontend and analysis engines are careful and battle-scarred; the seams are string-matched, show-hashed, and comment-asserted. Diagnostics have no source positions.
SOL
Great core, inverted priorities
Txn.hs is the best-engineered file in the profile. The interpreter was left quadratic while four acceleration tiers grew on top — the clearest ethos violation in the tree.
QOS + HAL
Coherent, at its complexity ceiling
One memory story, not several fighting — but ten hand-rolled recyclers and invariants enforced by comments. Two real memory bugs found.
USABILITY / DEPLOYMENT
Demo-strong, driver-weak
Full-stack todo app in 136 lines is a real result. But a fresh clone runs nothing, the stdlib is missing hour one, and the systemd appliance is ~25% real.
The one-paragraph verdict

This is a genuinely impressive solo systems project with a coherent worldview, and the ideas — rv64-as-shared-IR, whole-script transactions, WCET-composed std, first-class paths, gated hot-swap replayed from the disk — are consistently better than their implementations, which are consistently better than their integration. Measured against its own ethos, the tree earns "simple and elegant" in the compiler frontend, the memory-model design, and Txn.hs — and loses it precisely where performance was chased: the ~1,450-line Vec specialization tier, Sol's four acceleration tiers atop a pessimized interpreter, and the ten bespoke memory recyclers. The systemic disease is duplication (a forked "shared" frontend, five value walkers, six fold implementations, three static-analysis engines, golden strings in three places) and invariants that live in comments rather than code — which is exactly where the two real memory bugs below came from. As a thing to use today: superb inside its groove, missing the first hour of Python/Go outside it, and the Linux-appliance story is aspirational — the seat-owning binary doesn't currently have a build target.

Four cross-cutting themes

1 · The ethos holds at the core and breaks at the performance edges
Every place the tree violates "simple elegant code over premature optimization" is a performance tier:

Codegen's Vec specialization tier — Codegen.hs:1001–2462, ~1,450 lines: map/map fusion fixpoints, SoA fold dualization, RVV strip-mining, five near-copy-paste assembly emitters, and isGpuPairSum (Codegen.hs:2444) which special-cases literally \acc c0 c1 -> acc+c0+c1 to dispatch a GPU kernel. The tier's own comments record two "emitted, grepped for, never run" latent bugs. This is a hand-rolled optimizing backend bolted onto a deliberately naive code generator — and it's where the bugs have actually lived.
Sol's inverted pyramid — the interpreter core uses IORef (M.Map Reg Value) frames and fetches instructions with drop pc code (Sol/VM.hs:217–235) — O(log n) per register access, O(pc) per fetch, quadratic dispatch per function. The vestigial let codeArr = code marks an array conversion that never happened. On top of this sit an LLVM ORC JIT with per-callsite specialization (1,445 lines), a hand-rolled x86-64 assembler, a GLSL compute tier, and auto-memoization. A ~20-line IOArray/Vector fix would likely buy more across all workloads than the HandJIT tier buys on its narrow one.
Ten memory recyclers — buddy free lists, CAS buckets, bigfree LIFO, grant recycler, stack pool, acb arena, chblk free+limbo, ARC table, vec CoW rc, arena override pools — under three concurrency disciplines. Each fixed a measured leak; the aggregate is past its auditability margin (see the bugs below). The stack pool, grant recycler, and chblk backing are all "freelist of fixed blocks over big_block" and could be one mechanism.
BStr doesn't deliver its own bound — bsAppendStr (Sol/Val.hs:197–215) claims amortized O(1) append but rebuilds with strict-ByteString <> every time: O(n) per append, O(n²) for the loop it was invented to fix. All 11 HAL entries and the linear-typing ceremony are performance machinery that doesn't achieve its stated purpose.
2 · Duplication is the systemic disease
The README's "ONE frontend" is true only of the parser. Sol/Infer.hs (1,012 lines) vs Infer.hs (1,380 lines) share ~850 verbatim lines and have already diverged (F64/F32 and linearity shapes exist only in the AOT copy; the AOT header still says "inference … for Sol"). Sol/Lang.hs duplicates the desugarer, pattern compiler, lambda lifter, and linearity checker — plus a whole dead tree-walking evaluator (Lang.hs:513–649) mirrored by another dead copy in FPRISC.hs:1768–1861.
map/filter/fold exists six times (list interp, vec interp, LLVM list, LLVM vec, HandJIT, GLSL), each with its own hand-maintained "what is pure arithmetic" fragment — and they've drifted: Sol's operator is !=, but tabling, HandJIT, and Gpu whitelist /=, so != silently declines three tiers.
runtime.c:537–798: five hand-copied recursions over the identical tid-switch (dc_release/dc_size/dc_dup/kp_dup/has_vec). Every new tid must be threaded through all five.
Three overlapping static-analysis engines (Precond, StdCheck intervals, Safety's measure arithmetic), each with its own comparison-flipping table and its own decidable fragment; they already disagree.
The VList layout is restated in four places (vec.c:44–59 authoritative, then gfx.c:761–787, gfx.c:443–446, plus GPU paths hard-coding 16 << j). Golden output strings live in three (check-all.sh, qos.py's SMOKE table, #: expect headers). strEq is hand-rolled in 5+ .fpr files; and2/or2 in 13+.
3 · Invariants stated in comments, enforced by hope
The best comments in the tree state real invariants — and then nothing checks them. That's the exact origin of both verified memory bugs (below), the "the pass is deterministic per-bind so unit and root agree" seam in Compile.hs (separate compilation = whole-program passes re-run four times, an invariant that already broke once), the A64 TLS post-pass that pattern-matches an exact 10-line instruction sequence of text (A64.hs:382–394 — one changed emission comment is a silent miscompile), module identity as FNV-64 over derived Show output (Modules.hs:86–96, already patched once to survive an AST change), and name-magic conventions: postconditions ride a sibling sig literally named post_f, and any name containing the substring "unsafe" is treated as an unsafe extern (StdBridge.hs:266–267).

4 · Diagnostics are the structural debt that compounds monthly
No source positions survive parsing — the AST carries no spans, so every type, linearity, safety, struct, and precondition error is a location-free string ("in update: cannot unify Int with String") the user resolves by archaeology. Error categories exit one phase at a time, some to stdout and some to stderr, and runtime match failure prints raw AST (show of pattern constructors) at the user. Retrofitting spans means touching every pass, so it gets more expensive every month. This is the single biggest obstacle to anyone else using the language.

Verified bugs (checked against source by hand)

MEMORYSys.arena leaves bigfree uninitialized — runtime/runtime.c:800–807
g_arena builds its override pool on the stack and sets cur, allocated, buckets — never bigfree. Any allocation above the 8 KiB bucket ceiling inside an arena thunk reads stack garbage as a freelist head and walks it. Root cause is structural: fpr_pool_t has no constructor, so five creation sites each hand-initialize four fields, and the newest site forgot one. A ten-line pool_init() ends this class.
MEMORYVec.filter skips copy-on-write — runtime/vec.c:457–472
The CoW contract (vec.c:105–118) says "every WRITING op calls cow_wr first." fpr_vec_filter compacts rows in place and shrinks len without it — a dup'd or message-shared vector filtered by one holder silently mutates and truncates the other's view. Exactly the silent-corruption class CoW was added to kill. (The documented hole — specialized column loops not testing rc — is adjacent and should be closed at the same time.)
SEMANTICSSol auto-tabling is unsound-by-spelling and ON by default — Sol/VM.hs:142, 180; Sol/Main.hs:212
The purity gate treats any all-lowercase identifier as pure, so a helper that calls appendNow is "eligible"; IO makes the first call slow, which is precisely the keep-condition — after which repeated calls with equal args return cached results and silently skip the IO. A semantics-affecting experiment shipped on by default behind a spelling heuristic (plus chatty [table] diagnostics on stdout).
FRONTENDMalformed signatures are silently swallowed — FPRISC.hs:933–937
try (fullSig n) <|> (skipTillDot >> pure TSkip): any signature that doesn't parse becomes a no-op. Since signatures carry the unsafe markers, contracts, and StdCheck's all-Int safety declaration, a typo silently drops a safety contract and the program still compiles. Related: non-adjacent clauses of one function are silently dropped at desugar (FPRISC.hs:1560–1566 groups with span + M.fromList) while inference collects clauses by name across the whole file — the two phases disagree about what the program is, with no diagnostic.
TXNSol's transaction net has half-outside members — Sol/Txn.hs:199–217
txStat never consults the write view (write-then-stat reports the pre-write world, contradicting the script's own reads); txIsDir and the directory arm of txExists read disk directly and are never validated at commit, so a concurrent mkdir that changed a decision doesn't trigger the promised retry. The journal file (<script>.soljournal) is itself unlocked across concurrent runs of the same script. The core net — snapshot reads, buffered writes, sorted-lock validate/journal/replay — is principled and composes; these are periphery holes, and unlike stat/dirs, the stdout/sh escapes at least are documented.
HOSTqosp crash diagnostics are dead on Linux — qos/portable/main.c:325–345
bus_handler extracts the faulting PC only under #ifdef __APPLE__; on the stated Linux target, pc=0 and in_image is always false — the one thing the handler exists to report never is. And _exit(139) skips atexit, leaving the terminal raw/no-echo after any SIGSEGV.
DURABILITYNo fsync anywhere in the storage path — qos/portable/store.c:81–88; hal/unix/blk_raw.c:103–111
The kv store appends via buffered stdio and the block layer pwrites with no fsync/fdatasync, so the QLOG commit-flag ordering the .fpr layer carefully maintains is not actually ordered on the platter. DISK.txt's torn-write-rollback story is currently a design, not a property. Replay also silently truncates at a 256 KiB ceiling, and qa_load doesn't check malloc.
RUNTIMEThe actor layer panics the machine where an OS must degrade — runtime/actors.c:884, 1097; runtime.c:887
A full 64-slot per-sender ring, a ninth distinct sender, or a full 1024-entry ARC table each crash the whole machine. There is no backpressure primitive; any producer that outruns its consumer is a kernel panic. The ARC tombstone fix shows these limits get hit in practice.
LEAKHardcoded matrix library inside type inference — Infer.hs:909–931
inferBin pattern-matches operand records against the literal field lists ["w","x","y","z"] / m00..m33 and rewrites * into mulMM/mulMV globals that must happen to exist in the prelude — a library's naming convention baked into the HM engine, next door to the operator-site mechanism that shows how it should be expressed.
DEAD CODEVestigial mass worth a deletion pass
Target.hs — sold by the README as "the profile model" — is imported by nothing; the real model is five interacting booleans in Compile.hs:33–68 with only ~8 of 32 combinations meaningful and nothing rejecting the rest. hal/core/elfload.c (135 lines) is linked by no target. Two dead evaluators (FPRISC + Sol/Lang). A dead VBStr value variant beside the live table representation. ~330 lines of demo programs inside StdCheck.hs, whose header still says "CheckPoC.hs / Run: runghc". The exec/rw page check appears twice back-to-back in main.c:443–467. Plaintext passwords taught as "the shared sign-in pattern" in sol/lib/auth.sol:27.
The language as its users experience it

The apps and examples are the most honest testimony in the repo, and they say two things at once.

The constraint set shows up as ceremony, and scripts are managing it, not humans. No closures means hand-performed lambda lifting is the dominant texture of every non-trivial program: tuinotes.fpr threads seven positional parameters (con me stg notes count input buf) through a six-function continuation chain; std/mvu.fpr wears 42 unsafe markers in 449 lines, qlog.fpr 124 in 869. The paste-ready FPR_UNSAFE_SUGGEST tooling leaks inference gensyms (p36, c29, m35) into shipped source, and cliapp.fpr:108–119 contains the identical strEq signature duplicated twelve times in a row — the fixup tool stuttered and the compiler accepted it. Fallible pipelines become CPS-by-hand (editor.fpr's four named step-functions where Rust writes four ?s).

The stdlib is so thin that the basics are userland projects. Built-in == is tag-shallow, so safe string equality is a hand-rolled loop in five-plus files. There are no &&/|| operators; the and2 function is strict and therefore a trap the codebase documents having stepped on (tuinotes.fpr:51–53). No dict, no sort, no Option (one lib invents Opt2), no split/join/trim/replace, no argv, no env, no exit codes, no stderr, no JSON, no HTTP client; dtree.fpr hand-rolls log2 as 48 bit-squaring steps; base.sol's string helpers are O(n²) by construction. Sharp edges are commemorated in comments rather than removed (the float-interpolation segfault, 1-based charAt, strict-guard panics).

Where it's genuinely ahead of everyone KEEP

todo.sol: a complete multi-user, authenticated, persistent full-stack web app in 136 lines — Elm gives you the client only; Phoenix needs a project scaffold. This is a better demo than most young languages ever produce.
First-class @Model.path literals + schema tier + L.dump: every app gets a typed wire protocol and a free inspector. Rust/Go/Elm have nothing comparable.
Hot-swap with signature gates, replayed from the disk on reboot (sysdisk/selfhost tests): Erlang-grade live update with more static checking than Erlang.
Whole-script transactions with honest, named escapes (realtime, counted and reported) — no bash or Python equivalent for "atomic filesystem chore."
The capability preamble (P.hasGrant) is six honest lines with no analogue in the competition; linearity refusals name the variable and are asserted by exact message text in the test gate.
WCET-composed std with certified measures — the differentiator no competitor has, and check-all proves cross-tier bit-identity (dtree == GHC reference, qa64 == qx64 byte-identical, GPU == JIT == interp).
Against the competition, concretely
TASK	VS	HONEST CALL
MVU web app	Elm / Phoenix LiveView	FP-RISC's best story. One file, full stack, persistence included — genuinely less total work for a small app. Falls off a cliff the moment you need JSON, dates, or an HTTP client; string-typed messages are weaker than Elm's typed Msg.
TUI app	Rust ratatui / Go bubbletea	Wins on capability gating and immediate log persistence; loses on everything ergonomic — bubbletea's version is one struct + Update/View with a real string library and named keys instead of k == 127 via a strict or2.
Scripts / CLI	Python / bash / Lua	Not close. No argv, no env, no subprocess control, no dict, no sort, quadratic strings, no REPL, full-pipeline + LLJIT startup per invocation. Sol beats bash on safety in the atomic-file-chore niche and loses to it on reach. qos.py being written in Python is the honest verdict.
Numeric compute	Rust / Julia	Bit-for-bit GHC parity is impressive engineering, but the program hand-rolls log2 and argmax and threads linear handles through every pass. You choose FP-RISC here only for the WCET/bare-metal angle — which is real.
Time to first running program
On a fresh clone: effectively infinite until you reverse-engineer the toolchain. ./qos.py run tests/hello.fpr fails with failed (2): make -s fpr — and quiet=True swallows make's stderr, so the most common failure (missing toolchain) yields zero diagnosis. The actual prerequisites (GHC+cabal, LLVM 18 headers at the hardcoded Debian path /usr/lib/llvm-18 — baked into the .cabal file and three places in qos.py — qemu-system-riscv64, riscv64 cross-gcc) are documented nowhere. The README has no install section; NAMING.txt is a one-line stub; both NOTES.txt files are private scratchpads shipped as docs ("Sol should be done a bit better"). There is no CI. Realistic Ubuntu estimate: 30–60+ minutes; on Fedora/macOS you're porting hardcoded paths first. The bitter irony: once the toolchain exists, the on-ramp design is excellent — qos.py new scaffolds four working templates, dev gives rerun-on-save, pack --bundle emits a genuinely self-contained dist folder, and the #: plugins/#: expect self-describing-harness idea is elegant. The first mile of a good road is missing.

Readiness as a single systemd foreground service

Roughly 25% real, and the first blocker is upstream of packaging: the appliance binary has no build target. The DRM/evdev seat-owning qosp described by gfx.c + drm_scanout.h is unreachable from the build graph — the only target compiling gfx.c is portable-gl with -DFPR_DESKTOP_GL (qos/Makefile:63–67), which selects the GLFW-window branch and therefore requires a running X/Wayland session — the opposite of taking the seat.

Groundwork that already exists (and is good):

One foreground binary, meaningful exit codes, non-interactive via --yes/QOSP_YES, env-var config surface (FPR_DISK, FPR_HARTS, FPR_EVDEV, FPR_DRM…)
Journald-compatible by design: hostlog always mirrors to stderr, explicitly citing journald; app-visible /logs/host ring with replay
Panic last-words persist across restarts as a sys/panic kv record
Permission-aware probes that degrade and name their fix ("add the user to the input group"; DRM not-master → offscreen)
Loader integrity: sha256 verify → ABI gate → matched-set gate → W^X, every refusal named; tamper test in the gate
The gap checklist:

A buildable DRM/evdev appliance target (breaks first, before any permission question)
systemd unit, installer, make install, FHS/StateDirectory layout — all state is CWD-relative with no instance locking (two qosps silently interleave one kv log)
udev rules / group setup; privilege model (needs video + input; no drop, no capabilities). Network binds loopback-only (net_raw.c:59), which itself blocks networked appliance use
VT handling: no KDSETMODE, no VT_PROCESS — kernel console will scribble over the scanout; switching away and back unsupported; no logind/seat integration
Display cleanup: saved CRTC never restored, mode left set on exit (init/present exist, fini doesn't)
Hotplug: DRM probed once, keyboards enumerated once — a device plugged in after boot is invisible
Graceful stop: SIGTERM only restores the tty; no orderly actor-world shutdown → disk flush; no sd_notify/watchdog (and in-hart EAGAIN spin loops are undetectable from outside)
Durability: no fsync in the write path (see bugs above)
Predicted break order on a stock machine: can't build the DRM qosp → portable-gl needs a session → SetCrtc denied / console overdraw → input EACCES without udev → SIGTERM leaves the console bad.

Highest-leverage fixes, ranked

Fix the three memory/semantics bugs now: pool_init() + the g_arena bigfree init; cow_wr in Vec.filter (and the specialized-tier rc guard); tabling off by default (or a real effect check). All are small; all are silent-corruption class.
Prerequisites section + a CI image. One README section and one container/nix recipe converts "infinite" time-to-first-program into minutes, and makes the 12–15 min check-all sweep run on every push instead of when remembered. Un-swallow stderr in qos.py's build steps while there.
Source spans in the AST. The one structural refactor that gets more expensive every month. Everything diagnostic hangs off it.
A real base library: string equality/split/join/trim, dict, sort, Option, argv/env/exit-code — shared, not re-rolled per file — and unify the three stdlib vocabularies (prelude vs std.sol vs base.sol; map/fmap/sfold/foldl). This single item moves daily usability more than any tier.
De-fork the frontend. Make "ONE frontend" true: one Infer, one desugar/lift/linearity, one scheme-fragment judgment shared by interpreter/JIT/GPU/tabling. ~2,000 lines return, and the !=-class drift bugs become impossible.
Loud instead of silent in the parser/desugarer: error on unparseable signatures and on non-adjacent clause groups. Two small changes that close the worst "compiles anyway" holes.
Fix Sol's interpreter data structures (array frames, vector code) — then re-justify each acceleration tier against the honest baseline; delete the ones that no longer pay (Gpu and HandJIT are the candidates, per the ethos).
One deletion pass: Target.hs (or make it real), elfload.c, both dead evaluators, VBStr, StdCheck's embedded demos, the duplicated page-check. Cheap, and it makes the tree tell the truth about itself.
The appliance target: a portable-drm Makefile target, a unit file with StateDirectory=, two udev rules, VT acquire/release, a SIGTERM flush path, and fsync at the commit points. That list is the honest distance to "systemd service that takes the foreground."
What deserves explicit credit

So the review doesn't read as one-sided: qaimg.c and buddy.c are exemplary; Txn.hs's commit protocol (rename-atomic writes, redo journal with COMMIT sentinel, PID-stamped locks, SOL_CRASH_AT deterministic crash-window testing, and honest documentation of its own limits) is the best-engineered file in the Sol profile; deriving linearity shapes from builtinEnv so tables can't drift is exactly the right instinct — applied more widely it fixes theme 3; deep-copy message sends trading bytes for the elimination of four lifetime laws is arguably the best decision in the tree; the comment culture (real war stories at the point of use) is the best documentation in the repo; and check-all.sh, for all its one-liner-soup maintainability problems and tripled golden strings, is an unusually strong end-to-end gate for a solo project — negative tests asserted by exact error text are rare anywhere. The docs that exist are accurate on every spot-check; what's missing is the audience shift from design rationale to reference.

Method: four independent deep review passes (compiler core · Sol pipeline + libs · QOS/HAL C · language-as-used, each reading its full slice), synthesized and with all critical claims re-verified against source. Line references are to the tree at commit 614a9e9.
