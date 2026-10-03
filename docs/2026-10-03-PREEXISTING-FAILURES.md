# Five check-all failures that predated the stack fix

Date: 2026-10-03. Kind: bug record.

While verifying the ESP32-P4 stack fix (fprisc
`docs/2026-10-03-ESP-LIMITS.md`), `check-all.sh` failed four legs and hung in
a fifth. Every one of them also failed with the stack change reverted. They
came from the work merged in the days before:
- the relocatable app image (ABI v17);
- memory admission (`spawnWithHeap`);
- signatures that are never dropped (`daf0281`).

Each is fixed here.

## 1. The panic record hung: a log sink re-entered itself

**Leg:** "Log plane: panic last words persist".

**Symptom:** `qosp` spun at 100% CPU and the `sys/panic` record was never
written. Run alone the leg passed now and then; within check-all it hung
every time (0 of 6 trials).

**Cause.** The echo in `fpr_logput` holds the app's console lock while it
writes each byte through the host's `qos_console_putc`. When fd 1 stalled or
recovered, `qos_console_putc` reported it through `qos_hostlog`. That calls
the app's log sink, which is `fpr_logput` again, on the same thread, and it
spun for ever on the lock it already held. A sample of the hung process
showed exactly that chain:

    qos_console_putc -> qos_hostlog -> fpr_logput

`hal/unix/hostlog.h` already stated the rule this broke: nothing that runs
under the app's locks may reach the sink.

**Fix** (`hal/unix/hostlog.c`): the console's two notes ("not writable…" and
"writable again…") go to stderr only. They are about the console itself, and
stderr keeps every host line. **Result:** 6 of 6 trials persisted the record.

## 2. RELOC was not covered by any integrity check

**Leg:** "QAR2 integrity".

**Symptom:** the leg flipped the byte 100 from the end of `app.qa` and
expected "sha256 mismatch". Since apps became relocatable, an archive ends
with a RELOC section. The flipped byte landed there, and LOAD's `sha` covers
IMAGE only, so the tampered app ran.

This was a real gap, not just a stale test. RELOC says which words to move,
and IMPORT says what each slot is bound to. Both change what an image does
as surely as IMAGE does, and neither was checked: not for apps, not for
plugins.

**Fix.**
- **`tools/mkqa.py`:** a relocatable archive's LOAD gains
  `relsha <hex>` = sha-256 of RELOC followed by IMPORT. `mods/qaimg.fpr`
  reads it as the `Img` record's new eighth field.
- **Apps:** `qos/portable/qosp.fpr` checks `relsha` beside `sha`
  ("RELOC sha256 mismatch").
- **Plugins:** the app checks both hashes in `qos/appside/entry.c` before it
  allocates or places anything. A tampered relocation list must not move a
  single word, and the host's check runs after placement.
  - `qos/portable/sha256.c` is now linked into apps, and uses the compiler's
    builtins instead of `<string.h>`.
  - The host keeps its own checks as a second line: `qos_plugin_t` gains the
    `relsha`, `rel` and `imp` spans (ABI v18).
- **The leg** now locates IMAGE and RELOC from the archive's own table and
  flips one byte in each. It requires both refusals by name, instead of
  hoping that "100 from the end" is IMAGE.
- **`tools/plugimports-check.sh`** adds `plugtamp.qa`: `plugmini.qa` with one
  RELOC byte flipped. It is refused ("RELOC sha256 mismatch") before
  placement.

**Not done:** the native kernel's process loader checks neither `sha` nor
`relsha` (`programs/system.fpr` `runProcess`). That gap predates this one.

## 3. Sol had no `spawnHeap`

**Leg:** "sketch tier".

`std/mvu` now starts its workers with `std/actor`'s `spawnWithHeap`, whose
primitive `spawnHeap` existed only natively, so `tests/sketch-mvutick.sol`
failed to type-check under Sol.

**Fix** (fprisc `compiler/Sol/VM.hs`, `Infer.hs`, `Preamble.hs`): Sol's
`spawnHeap bytes f` spawns and answers `Ok pid`. Sol's actors share the
Haskell heap and have no per-actor budget, so the grant is not enforced. This
is the same treatment `spawnCap` already gets for its mailbox capacity.

## 4. `mlpipe.sol` named a type that does not exist

**Leg:** "Sol ML pipeline".

`mkPt : Int -> Int -> Int -> {z : Numeric, y : Numeric}` named `Numeric`, but
in Sol `Numeric` is the struct of arithmetic operations, and the one number
type is spelled `Int`. Record types in signatures used to be dropped, so this
was never checked. Since `daf0281` they are checked, and the script stopped
type-checking.

**Fix** (fprisc `sol/examples/mlpipe.sol`): `{z : Int, y : Int}`. All three
tiers agree again.

## 5. The dedup ratchet: `Sol/Lang.hs` at 246 of 244 lines

**Leg:** "dedup ratchet".

`daf0281` taught both of `Sol/Lang.hs`'s type-name renamers about record
types, one line each.

**Fix** (fprisc `compiler/Sol/Lang.hs`): the two renamers were near-copies.
They are now one top-level `renameTypeNames`, which each applies with its own
renaming. The file is back at 244, by merging rather than by raising the
ceiling.

`Sol/Infer.hs`'s ceiling rose from 126 to 127, recorded with its reason in
`tools/dedup-ratchet.sh`. The new line is item 3's `spawnHeap` declaration, a
primitive, not inference machinery, which is the growth the ratchet's
comment allows.

## Also seen once

"HostedBytecode (sol)" failed once in a sweep and passed on rerun. It was not
reproduced.
