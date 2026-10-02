# Graphics.qa: one owner of the display, programs as sessions

Date: 2026-10-02. Kind: implementation record. Convergence item 5 of
[2026-10-02-QOS-ARCHITECTURE-AUDIT.md](2026-10-02-QOS-ARCHITECTURE-AUDIT.md)
as restated in [2026-10-02-QOS-AUDIT.md](2026-10-02-QOS-AUDIT.md), with the
part the audit asked for that can be verified without a display done here,
and the part that needs one stated as such. QOS revision: the commit
carrying this page. Source: `programs/mods/graphics.fpr` (the service),
`programs/mods/glsvc.fpr` (the GL backend and the single-program
wrapper), `tests/gfxshare.fpr`.

## What it is

The GPU tier (`hal/unix/gfx.c`) is one thread-bound context, one window,
one FBO. Until today every graphical program spawned its own GL actor
over it, so two could not share a machine. `Graphics.qa` owns it now.

A program is a **session**, keyed by its pid: every actor of the program
speaks for it, the MVU render worker included, and the actor that opened
the session (or spoke first) is the one whose end is the session's. The
**focused** session's frames are drawn and its polls get the input; the
others keep running their loops and are answered `(0, 0)` and no input,
a frame they did not pay for. F1 cycles focus and is swallowed. A session
closed through the contract, or whose owner has died (`Sys.alive`,
checked on the next frame anyone sends), is dropped and the focus moves
on; a new open is a new session. The service never stops.

Two protocols meet in the one actor. Through the namespace, the endpoint
contract: open `/services/graphics/<tag>` for a session, write a session
`"<name>\n<mesh text>"` for a program-carried mesh, read it for the
dimensions, open `/services/graphics/focus` for the control handle, write
it a tag to focus, read it for the session list. Straight to the owner,
`std.MVU`'s render and input protocol: `Dims`, `Render`, `Poll`, exactly
what a program's game loop already speaks. A program that speaks `Rv`
without an open is admitted as a session of its own, which is what
`GL.serve` now is: a private service with this backend and the program
its one session. The Xvfb legs (Terra II, the dungeon, the walker tests)
run that path unchanged.

The backend is a record of functions, not an actor: the scene is walked
from the frame message itself, in the service actor, the context's one
caller, with no copy. `glsvc.fpr` supplies the GL record; the test
supplies a stub that reports every frame it is asked to draw.

## What is verified

`tests/gfxshare.fpr`, headless, in the smoke set and the full sweep: two
MVU programs under their own pids open sessions and run; the first opened
is drawn and the second is not while its loop runs; a write of the tag
focuses the second and the first stops; the first quits and closes and
the second is still drawn; the first is started again as a new session,
undrawn until focused, then drawn while the second is not; the second is
killed while focused and the next frame moves the focus back; the control
handle lists both. The GL programs (Terra II, the dungeon, `gl2d`,
`gfxmesh`, `gltext`) compile against the new backend.

## What is not

No display on this machine runs the GL backend under the service, so
Terra II beside a second graphical program on real pixels is not shown
here; the Linux legs under Xvfb run one program each. Focus is one
program at a time, full screen: there is no composition of two sessions
into one frame, and no window geometry. The input routing is to the
focused session only; a program that wants a key while unfocused does
not get it. `hal/unix/gfx.c` is unchanged: the scene walker, meshes,
text and camera policy are still C under small FP-RISC calls, which the
audit lists separately.
