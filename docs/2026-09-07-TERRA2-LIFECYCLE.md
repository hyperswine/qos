# Terra II: lifecycle, persistence, cards and terminal

Kind: dated implementation/measurement record. Date: 2026-09-07.
Source additions: b83fb4f, bc7fd9d, aaa2551, 4ebfdaa and be71e56 (2026-09-07).
Extracted without reconciling historical claims on 2026-09-29 from
[TERRA2.md](2026-09-04-TERRA2.md). No historical checks were rerun.

## The lifecycle

A packaged game has screens, and the model now says which one is up:
title, playing, paused, game over, keys, stats (`screen`).  Paused,
Keys and Stats freeze the tick -- animations, the AI and the supply
ticker stop, only keys are taken -- and the music ducks to half while
paused.  Esc with nothing selected pauses: a glass menu over the veiled
board with Resume, Restart, Stats, Keys and Quit, arrows and enter.
Restart asks first ("Abandon this game and deal a new one?") so a stray
key cannot wipe a game; the new deal keeps the profile, the settings
and the snapshot counter.  K and S open the Keys and Stats screens from
the title, the menu and game over, and esc, enter, K or S return to
where you came from.  The Keys screen is a table (`keymap`) that is also
the source of the unit panel's key caps, so the two cannot drift.

## The profile

The disk keeps a profile: one append-only record at `terra2/profile`
on the QLOG log through `std/fs` (the same service POS uses), a line per
event -- `start <seed>` when a game is dealt and `end <seed> win|loss
<rounds> <hqMe> <hqEn> <called> <lost> <destroyed> <damage>` when an HQ
falls.  Boot replays the log and folds it into totals; every line the
game writes is folded into the model's copy first, so the Stats screen
never lags the disk, and update flushes the pending lines after each
step (the rules never touch the service).  A start with no end is a
game abandoned.  Stats shows played / won / lost / abandoned and the
win rate, the best win in rounds, the average length, units called and
lost, and the recent games one line each.  The GL host opens
`qosp.disk` beside it (or `FPR_DISK`), so `./qos.py run` and a packed
bundle keep the profile between runs without any flag; with no disk the
game says so on the Stats screen and plays on.  Boot also asks the
storage service to compact (live records copied forward, the log
truncated -- idempotent), so a long-played disk does not fill with
superseded saves.

## Continue

The board is saved too: at `terra2/game`, whenever a turn of yours
begins (the state after income, nothing in flight -- `dirty` is set by
the turn start and the save goes out with the next flush that finds the
board idle) and cleared when an HQ falls.  Only what the rules need
goes out: both sides (HQ, supply, deck, hand, the two rows as eleven
numbers a unit), turn, ENV, the counters; never the animation, cursor
or queue.  Boot reads it back under the title -- the saved board is
what the camera drifts over -- and the prompt becomes "ENTER continue
turn N / N new game".  Continue picks up at that turn with no start
record; N deals fresh.

## Cards

C from the title, the pause menu or game over opens the Cards screen:
both factions as small cards eight to a row (name, cost badge, kind,
figures), the cursor's card in a detail line below with its full stats
and a line on what its kind does; arrows browse, up and down swap
faction.  The same card component the hand uses, so the screen doubles
as a check that every card in the table renders.

## Staying inside the box

The 2D layer's text and cards used to run past their containers.  The
walker now carries a clip rect per instance (docs/2026-09-05-UI2D.md, `Clip`), so
the hand is a centred carousel: cards beyond the edge are cut, the
strip follows the cursor's card when the cursor moves, and the wheel
scrolls it in place while the cursor is in the hand.  The Stats
screen's list of games scrolls under the wheel the same way.  Text
that would overflow -- the message line, the panel's status line, card
names -- is capped and cut with "..".

## The terminal

T opens a terminal over any screen (esc closes it): the model as a data
console, the same idea as the POS's admin tab.  `get PATH` and `set
PATH N` read and write the shop of numbers the rules run on -- `me.hq`,
`en.stock`, `env`, `tno`, `seed`, `music`, a unit at `me.fwd.3` with its
`.hp .atk .ready .mode .down .chg .vet` -- and `ls` lists the paths.
`hand me|en` and `board` print the cards and the rows; `deal`, `place`
and `clear` put cards and units where you want them; `hit me|en N` goes
through the rules' own HQ damage, so victory and defeat apply.  Typing
comes from the evdev codes (letters, digits, space . - = , /), so a
replayed key file types too, and every line with its answer goes to the
transcript as `term:` lines.  The check types `get me.hq`, `set env 4`
and `board` from the title and reads the answers back.

