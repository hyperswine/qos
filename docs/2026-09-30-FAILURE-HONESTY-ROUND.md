# Failure-honesty follow-up

Date: 2026-09-30. Local implementation follow-up to the QOS architecture audit.

## Storage replies and pins

`programs/mods/svc.fpr` checks the result of sending a storage request and waits
with `receiveFromRes` for the storage actor. Refusal and death return `Err`;
unrelated messages from other actors remain queued. The accepted result is kept
before releasing its mailbox envelope. `programs/system.fpr:storeRpc1` delegates
to that same helper, so native storage uses the tested implementation.

Module publication order was `svc`, then `qlog`, then the system pin, then
`./qos.py lock`:

- `svc.v1.6#499b714b4dea5853`
- `qlog.v2.3#40c524a7bd2900c1`

`tests/storerpc.fpr` tests unrelated queued `Result` traffic, actual storage
reply, dead storage, full mailbox refusal and no disk. `check-all.sh` includes
it. The caller remains synchronous: sender selection is not correlation between
multiple concurrent outstanding requests to the same service.

## Baseline and QSys coverage

`tools/qsys-check.sh` builds the QSys app and two plugins, seeds a fresh disk,
and boots twice without reseeding. It checks both plugin export results and
that `/tmp/note.txt` grows from 3 to 6 bytes. The fixture now also checks the write
receipt, so failed persistence cannot be hidden by reading an earlier value.
This two-boot test is included in `check-all.sh`.

The sketch leg uses explicit-output hosted fixtures for paths, hello and MVU.
The text-tool assertion matches the current structured listing output. JSON/CSV
checks the current opt-in success receipt and verifies the resulting files with
Python's JSON/CSV readers. `both.sol` explicitly declares base for its native
run; it also runs as a hosted sketch through `fpr sol`.

QOS's shipped service and standard-library trust entries live in
`core/trusted-modules.txt`. This is an explicit transitional source allow-list,
not a proof certificate, and arbitrary newly imported files are not added to it.

The sweep also exposed stale ML/NN expectations and an RVV boot failure.
ML and NN explicitly request verbose compilation receipts; absent GPU dispatch
is reported as a skipped GPU assertion while JIT/interpreter checks still run.
NN's over-general signatures were narrowed in the example. RVV now enables V
state before C startup on each hart, including compiler-vectorized init code.
The focused NN and RVV execution checks pass.

## Verification

Fresh storage failure test: passed. Two QSys boots: passed, two plugins,
`ping=pong`, `21+21=42`, note 3B then 6B. Existing QSys failure test: passed.
Compiler failure-honesty, Sol output, safety, transaction/recovery and cache
checks passed. The final `sh check-all.sh` sweep completed with exit status 0 and
`ALL LEGS GREEN`. The output is saved locally at
`/tmp/failure-honesty-sweep.out`. It includes the repaired sketch, both-profile,
text-tool, JSON/CSV, ML, NN and RVV legs, plus the new QSys, storage and
compiler failure gates.

## Coverage still open

The graphics and alternate-AArch64 legs require unavailable Linux/GL/QEMU
prerequisites on this Mac; websocket tests need Python `websockets`. No GPU
dispatch was observed here, so only JIT/interpreter and fallback agreement can
be claimed.

A separate check-only scan of 66 concrete `PROG` inputs from the harness found
65 compiling and a pre-existing `tests/gl2d.fpr` error: `scene2d.fpr:dynGo` and
`diGo` omit the `Ent` constructor alternative. The skipped graphics leg does
not exercise that compile failure. It is outside this round and remains open.
The legacy all-Sol-examples tally is also informational rather than an enforced
gate. It reported 38/47 after the NN fix; the nine unresolved demonstrations are
`physics`, `prolog`, `bboard`, `dash`, `todo`, `mandel`, `terra`, `pos` and
`dtree`. Their type errors are not certified away by an active-leg
`ALL LEGS GREEN` result.
