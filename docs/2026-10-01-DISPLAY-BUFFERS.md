# The display in O(1) memory: two buffers in one linear Vector

Date: 2026-10-01. Kind: implementation record. Closes the "Still open" item of
[LAUNCHER-IDLE](2026-10-01-LAUNCHER-IDLE.md), and is the first step of the
order agreed for removing privileged identities: display, then relocatable
process images, then the Portable import table.

## Before

`TUI.frame` rendered a widget into a fresh `List (List Int)`, diffed it
against the previous one, and returned the new list as the cache for the
next frame. The launcher kept that list in its own pool, which is reclaimed
only when the actor dies. The LAUNCHER-IDLE doc estimated "about one 80x24
buffer per second". Measured, it was much worse: a frame bumps about
**236 KB** from the actor's pool (the widget tree, the rows, the diff's
lists). `tests/tuiframes.fpr` reports 71 MB over 300 frames. An idle launcher
redraws once a second for its clock, and on every key.

## The mechanism

Nothing here is specific to the display. It is an FP-RISC Vector and memory
from the actor's pool. There is no frame-buffer object and no identity
beyond a value.

- **Two buffers, one Vector.** `TUI.screenNew w h` makes one linear Vector
  of 2·w·h packed cells. The front half is what the terminal shows, the back
  half is the frame being drawn. The front starts invalid (cell 1 matches no
  cell), so the first frame paints everything.
- **A frame swaps them.** `TUI.frameV w v fo widget sz` does three things:
  1. renders the widget;
  2. for each row, finds the columns that differ from the front and writes
     the row into the back half in place (`Vec.put`);
  3. emits the merged runs through the same ANSI code as before.

  It returns the back offset, which is the new front, and the Vector. That
  is the swap: an Int flips, nothing is copied.

  `TUI.screenInvalidate v fo n` marks the front invalid. The launcher uses
  it after an app has had the screen.
- **The loop is `Sys.loopWith`** (fprisc `docs/2026-10-01-LOOPWITH.md`). Each
  step runs in an arena, and only the small state is copied to the next
  step. The Vector threads through by identity. Everything a frame allocates
  dies with its step, and the launcher's own pool does not grow.

The list API (`frame`, `invalidBuf`, `diffFrame`) is unchanged for other
callers. The module is `tui.v1.1#88e6fe357f5d8603`, a patch that is
signature-compatible with v1.0, and `system.fpr` pins it.

## The launcher

`launcherLoop` (`programs/system.fpr`) makes the screen once and runs
`Sys.loopWith (TUI.screenNew 80 24) (1, page, 0) (fn st v -> lStep caps ids st v)`.

- **State** is `(sel, page, front offset)`.
- **A step** draws a frame, then waits for a key or the next clock second
  (`lPoll`, still in a nested `Sys.arena`, still parking 1 ms between empty
  polls), then acts on the key.
- **`q`** returns `False` and ends the loop.
- **A launch** (`lRun`) runs inside the step. When it returns, the front is
  invalidated and the next frame repaints in full.

## Verified

`tests/tuiframes.fpr` (QOS smoke, `display O(1)`) redraws a status screen
whose header changes every frame and whose marker moves down the rows. It
does this two ways, each emitting through a counting actor.

| | Lists (`TUI.frame`) | Screen (`frameV` + `loopWith`) |
|---|---:|---:|
| bytes / writes on the wire, 300 frames | 62,646 / 921 | 62,646 / 921 |
| actor pool growth, 300 frames | 70,976,112 B | 65,952 B (one-time, the first loop) |
| actor pool growth, a further 5,000 frames | -- | 224 B |

The wire output is identical, so the diff is unchanged. The lists run is in
a child actor, so its leak dies with it, and the heap's free total ends
within 1% of where it began.

A first version of the test compared totals read by a different actor than
the one that wrote. That was a race: the last write and the request for
totals came from two senders, so the order was not guaranteed, and one run
counted a write fewer. The writer now asks for its own totals.

## Not done

- The step-local garbage is still large: a frame builds its widget tree as
  lists, then copies it into the back half. Widgets that draw straight into
  the Vector would remove most of it. It is now a constant per frame, not
  growth.
- A terminal size other than 80x24 needs a new screen. `loopWith` refuses a
  vector whose storage moved, so a resize ends one loop and starts another.
- No native idle test beyond the existing check-all legs: they boot the
  native launcher and launch from it.
