# Bounded inboxes on the inline path; the mailbox ARC leg

Date: 2026-11-10. Kind: a fix, measured, plus the sweep.

Follows [ACTOR-ROUND-TRIP-STEPS-2-3.md](2026-11-10-ACTOR-ROUND-TRIP-STEPS-2-3.md),
which left two open items: bounded inboxes kept the ordinary message path,
and fprisc `tests/mailbox.fpr`'s 3000-message ARC leg no longer reached the
ARC table. Both are fixed in fprisc `20ad433` on branch
`qosapp-receive-loops` (on top of `fa36d06`; not merged or pushed). QOS
main `4e60743`, `fprisc.lock.json` unchanged.
Evidence: [evidence/2026-11-10-bounded-inbox-inline/](evidence/2026-11-10-bounded-inbox-inline/).

## 1. Numbers

QOS Portable, `./qos.py run tests/ipcbench.fpr --harts 2`, three runs after
a warm-up:

| Case | `fa36d06` | `20ad433` |
|---|---:|---:|
| same | 95-98 ns | 93-95 |
| same bounded | 161-164 | **112-113** |
| cross | 203-214 | 200-207 |
| cross bounded | 329-349 | **287-297** |

The other cases are unchanged within noise. Bar: null syscall 75-98 ns.
`same bounded` is ~17 ns over unbounded: the reservation takes the inbox
lock and the publish takes the channel lock, where the unbounded publish
takes none.

## 2. How a bounded inline send works

`send_inline` (fprisc runtime/actors.c):

1. resolves the channel under `shlock`, as the ordinary bounded path does
   (reap clears the channel block under it);
2. on the channel's first inline send, installs a same-size ring with a
   cell area and the per-slot charge words;
3. reserves the message's charge (`inbox_reserve_bytes`);
4. under `shlock`, re-checks death and room, writes the cell, the slot and
   the charge word, publishes, and commits the reservation. On any refusal
   it cancels the reservation and the ordinary path answers.

Nothing between 3 and 4 allocates or parks, so the reservation is
committed or cancelled in the same call. The receiver already released the
charge word of whatever slot it takes, the middle-of-queue shift and death
drain included.

**The charge is exactly the ordinary path's.** That path charges the
whole message slab the copy would go into (64 KiB at least, rounded to a
power of two), not the message's own bytes. An inline message is one cell
of `PREHEADER` bytes, so its charge is the same formula applied to that
(`charge_bound`, now shared with `fpr_msg_charge_to`) with no walk.
`FPR_INBOX_TEST` builds compare the two on every inline send. So a limit
admits the same messages whichever path carries them. A byte limit of
512 KiB still admits only 8 small messages; charging the true size would
admit far more. That is a separate decision, left as it is.

## 3. Tests

- `tests/base/inlinebounded.fpr` (new; copy in the evidence directory):
  - a 5-message limit takes 5 of 8 and refuses 3, and is whole again once
    the receiver has taken them;
  - order is kept with refusals in between;
  - a 512 KiB byte limit admits 8 slot-carried and 8 ordinary messages;
  - a result is taken from behind three slot-carried messages, and the
    charges are released.

  Same output on `20ad433` and `afcb0a0` at 1, 2 and 4 harts, and with
  `FPR_INBOX_TEST`.
- fprisc `tests/check_inbox.py` (inbox, inboxshared, inboxownership,
  inboxkill, inboxadmission at 1 and 4 harts): all HOLD.
- Differential run (154 programs from `tests/base` and `tests/edge`,
  harts 2 and 4, against `afcb0a0`): same exit codes and digit-stripped
  output.
- fprisc `tests/mailbox.fpr`: the 3000-message trial now sends
  `(i, (i, i * 3))`, a nested pair, which stays an ARC entry while queued.
  It reads `arcLive` with all 3000 queued and prints
  "3000 queued but only N ARC entries held" if the table did not hold them.
  With flat tuples it prints N = 9; with the nested pair the line the
  check-all leg expects is unchanged.

## 4. check-all with `20ad433`

Run with this branch's `tests/arcaudit.fpr` edit applied:
**145 passed, 9 failed, 9 skipped**, the same as step 1 (`3484418`), with
the same nine known failures. ARC.qa and liveboard, which failed with
`fa36d06`, pass. `legs-20ad433-qos4e60743.tsv`.

## 5. Left open

- Cross hart, bounded or not, is ~200-290 ns, 2-3x the bar.
- The slab-sized charge for small messages (section 2).
- The arcaudit edit has to land with the pin that brings this fprisc.
