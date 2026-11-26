# MVU alignment: QOS pointer (26 November)

Kind: pointer to a statement of intent. Nothing here is implemented yet.
Applies to qos `main` at `988d7296`.

The review of the 26 November MVU changes (`AS.run`, `D.Log`, named keys in
`appwire` and the desktop SDK) and the intent that follows from it are
recorded in FP-RISC:
[docs/2026-11-26-MVU-ALIGNMENT-INTENT.md](https://github.com/hyperswine/fprisc/blob/main/docs/2026-11-26-MVU-ALIGNMENT-INTENT.md).

What it means for QOS:

1. Release the Portable SDK 0.7.0 with `D.Log` and the key names, so
   grapher's desktop app builds on a released SDK (`desktop-v0.6.0` has
   neither).
2. Take the key codes and modifier helpers from one FP-RISC `std/keys`
   instead of the copies in `programs/mods/appwire.fpr` and
   `sdk/qos/desktop.fpr`.
3. Replace `AS.run`'s `updateFn`/`viewFn` (`programs/mods/appsession.fpr`,
   reported by the compiler as `<dynamic>` callback calls, against the rule
   in `2026-10-29-INSTALLED-DESKTOP-SDK.md` and
   `2026-10-18-QOS-DESIGN-ALIGNMENT.md`) with a specialized per-app loop, or
   record a deliberate change to that rule. Issue initial-resize commands the
   same way in native and SDK apps, and stop requiring a `phase` field.
4. Add commands or subscriptions for process start, policy reads and runtime
   statistics, then move the effects out of editapp's and termapp's `update`.

Unifying the MVU surfaces is a later step and not part of this.

## Status (26 November, later)

Item 3 is decided and done the simpler way: `AS.run` keeps its callbacks and
the rule is changed. See
[The shared app loop takes application callbacks](2026-11-26-APP-LOOP-CALLBACKS.md).
Item 2 waits for a pin move: FP-RISC has `std/keys` on its
`zero-cost-named-keys` branch.
