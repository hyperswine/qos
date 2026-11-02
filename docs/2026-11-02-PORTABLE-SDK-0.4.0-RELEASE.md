# QOS Portable SDK 0.4.0

Status: publication held, 2 November 2026. Homebrew remains on SDK 0.3.1.

This updates the complete SDK to FP-RISC revision
`858238cbc7500f5da8bd8dda2a132fc1aa0251c9`, with QOS source
`be81ff746fddaeab0c0d20f84509c49bcaf100cc`. The private compiler, runtime
platform sources and AArch64 context switch are matched. Both hosts, Main,
six bundled apps and the acceptance driver were rebuilt with this compiler.
The static ELF linker is retained. The compiler hash is
`c70c7acbd3c089f3080ffcc0555d053f36fc928a0423cb97cf0fcd75a385f5c0`.

The ABI moves from `22.137` to `22.143`. This is a new SDK minor series so
existing `0.3.x` pins keep selecting the older compatible SDK. Native apps
must be rebuilt, and existing native disk profiles are refused without
changing their bytes. There is no automatic disk/profile migration in this
release. Keep the matching 0.3.x SDK for existing disks until their apps and
profile are deliberately migrated. User stores and defaults are preserved.

The SDK remains macOS ARM64, minimum macOS 27.2. Native builds require Clang
and the indexed libgit2/libarchive/GLFW dependencies. It needs no source
checkout, GHC, Cabal, Python or external lld. Its native builder retains the
strict compiler/SDK pin policy shipped in 0.3.1.

Qualification uncovered two compiler issues, fixed in the pinned source:

- The ownership checker used a same-named global function's result and
  constraints for a local callback. Terra II's root `key` handler therefore
  affected `std/list`'s local `key` callback. Local names now take precedence;
  a locally bound `error` callback also retains normal call semantics.
- Imported resource contracts triggered equations for unrelated application
  functions. Terra II's implicit check grew to a sampled 26.6 GB footprint.
  Implicit checking now derives every declared work/allocation/live contract
  and its transitive dependencies. It still rejects invalid unused contracts.
  Explicit `--cost` reports and target manifest judgements retain the full
  program view. Terra II passed frontend checks with its configured 2 GB heap
  limit after this change. This is not a claim that arbitrary explicit cost
  reports have bounded compiler resource use.

All 36 compiler unit suites and the cost regression suite passed, including
unused invalid contracts, higher-order composition, manifests and reports.
The candidate archive was frozen after these checks. Its SHA256 is
`261c5f18638b622b2cc14cfe259564addf5ca3609eeca0fa64b883f08b6cd7d6`.
The exact tarball passed installed graphical Main and persistence acceptance,
external Dungeon and Terra II gameplay, platform override/tamper checks,
native/reference command parity, seven packaged SDK pin cases and ABI refusal
with unchanged old disks. Eight host C groups and nineteen SDK policy groups
(including twenty native/reference version cases) passed. An installed process
with twelve live FP values survived forced yields and recursive stack growth
on one and four harts; the independent context oracle and its negative control
also passed.

The complete two-worker service sweep passed **15 of 16** groups. Preferences
failed its endpoint retention assertion: no more than eight extra ARC roots
and less than 2 KiB extra arena use. Publication is held; no release tag,
GitHub release or public index update was made.

An instrumented comparison with the new pair and the existing SDK 0.3.1 pair
produced identical counters. The unmodified preferences test also fails with
the old SDK pair, confirming that this gate already fails before the upgrade.
The instrumented roots were 55 -> 71 after 500 updates, then 21 after
1,000 more; arena ledger 11520 -> 11776, then unchanged. This does not establish
an unbounded leak or explain the failed assertion. Longer settling waits,
warm-up, temporary arena isolation and reordered probes did not resolve it.
The original test limits are unchanged. The remaining work is to explain and
resolve this gate before promotion, rather than publish around it.

[Machine-readable evidence](evidence/2026-11-02-portable-sdk-0.4.0-release.json)
retains the complete service results and diagnostic logs. The candidate is
preserved on `sdk-0.4.0-candidate`; main retains its previous compiler
pin until the candidate is admitted. All testing here is hosted macOS ARM64,
not a new Pi deployment or an automatic native-disk migration.

During final sync, FP-RISC main also gained independent list-fusion and fuel-tick
changes. The tested compiler pin is retained on FP-RISC's
`qos-sdk-0.4.0-compiler` branch. Refresh the candidate to the then-current main
and requalify it before promotion; the evidence here belongs to the frozen
compiler above.
