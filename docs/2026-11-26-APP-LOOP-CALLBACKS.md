# The shared app loop takes application callbacks (26 November)

Kind: design decision and implementation record. Branch
`as-run-design-rule`, from `main` at `183ec09`. Step 3 of FP-RISC's
[MVU alignment](https://github.com/hyperswine/fprisc/blob/main/docs/2026-11-26-MVU-ALIGNMENT-INTENT.md),
which offered two designs. The owner chose the simpler one on 26 November:
keep the shared loop and change the rule.

## The decision

`AS.run me init update view` (`programs/mods/appsession.fpr`) stays. It is
the one MVU loop of the in-tree apps that have no control or preference
sidecar: browser, clock, disk and logs. It takes the app's `update` and
`view` as function arguments.

This changes a rule that three places stated:

- `appsession.fpr:1-2` said the module "never accepts an application
  callback". The comment now says what `run` does.
- [Installed desktop SDK](2026-10-29-INSTALLED-DESKTOP-SDK.md) says the
  generated adapter "does not move application callbacks into a trusted SDK
  loop". That remains true of the adapter and of installed SDK apps, which
  never come through `AS.run`.
- [QOS design alignment](2026-10-18-QOS-DESIGN-ALIGNMENT.md) says the trust
  list "does not grant an application callback a safety exemption". That
  also remains true: `appsession` is an `unsafe module`, but the functions
  passed to `run` are compiled and checked in their own modules under their
  own safety line. `run` calls them; it does not vouch for them.

## What it costs

The compiler reports the two calls as
`remark[generic-call] callback specialization attempt for <dynamic>`. They
are indirect calls: `update` and `view` are not inlined into the loop, and
the per-step work bound does not see through them. One indirect call per
event and one per frame is accepted for four small apps in exchange for one
copy of the transport, sequencing and shutdown code. An app that needs the
calls resolved keeps its own named loop, as editapp and termapp do, or is
built through the generated adapter.

## The contract, now the same as the SDK adapter's

```text
init                          : (model, List AW.Cmd)
update AW.Event model         -> (model, List AW.Cmd)
view (width, height) model    -> (scene, List String, status)
```

Two differences from the adapter (`tools/desktop-adapter.fpr.in`) are
removed:

- **First Resize.** `AS.run` discarded the commands `update` returned for
  the initial `Resize`; the adapter issued them. `AS.run` now issues them
  too, after init's commands. The four apps return no commands on `Resize`,
  so their behaviour is unchanged.
- **Status.** `AS.run` read an implicit `phase` field from every model. The
  status text is now the third component of what `view` answers, as in the
  adapter. The four apps answer `AW.status m.phase`.

## Checks

- `tests/apprun.fpr` (new): a probe app over `AS.run` asks for the clock on
  its first `Resize` and reports in its status whether the answer arrived.
  Built with `sol tools/checkout.sol pack tests/apprun.fpr --bundle` and run
  on QOS Portable (macOS arm64, 1 hart): `apprun: HOLDS`.
- The six apps of the CI type-check (browser, clock, disk, editor, logs,
  terminal) type-check for `qx64`.
- Both were run with the FP-RISC working tree (`f607eb59` plus the nullary
  literal fold), not the pinned `73e8fd31`.

## Found on the way, not fixed

`tests/appsession.fpr` panics on QOS Portable with
`Int: expected Int or BigInt` after "editor: build x.fpr: failed at line 2".
It does so on unmodified qos `183ec09` with FP-RISC `main` `f607eb59`, so it
is not caused by this change. It was not run at the pinned compiler.

## Not done

- The SDK-side behaviour was already the target; no adapter change.
- `mods/gamerun.fpr` takes `Game.app init update subs view` and draws the
  same `<dynamic>` remark (for example at `gamerun.fpr:96`). The same
  decision covers it; nothing was changed there.
- The GUI check and the Pi were not run.
