# Opening the Editor no longer panics the shell (28 November)

Kind: bug record. Branch `fix/qsys-actor-compare`.

**Symptom:** on the desktop shell built with SDK 0.6.1, opening the Editor panicked the whole
shell right after `creating /home/.editor/session`, with `[ERR] Int: expected Int or BigInt`.
The Pi runs the same shell code.

**Cause:** under lldb, the panic is in `qsys`'s per-file actor (`fileTimed`, through the inlined
`fileRetireWith`), at the comparison `mgr > 0`. The value it rejects has type tag 9005, an actor
handle. FP-RISC's exact `Int` now checks `>` operands, and an actor handle is an opaque value,
not an integer. The file manager and its file actors tested handles with `> 0` in several places:
- a file actor going idle;
- retiring;
- the admin checks;
- the manager's reclaim walk.

The Editor's session file reaches the first of these when it goes idle.

**Fix:** compare handles only with `==` / `!=`; `0` still means no actor. The change is the
`qsys` part of `1802d24` on the `apps-as-files` branch, where the desktop-apps session found the
same panic. It is taken here alone, so it lands without that branch's file moves.

**Check:** the shell built with SDK 0.6.1 plus this `qsys` (and the drop-park runtime hotfix)
opens the Editor on a fresh disk without a panic, takes typing (a snapshot shows the typed line
at Ln 1, Col 12), and stays idle afterwards.
