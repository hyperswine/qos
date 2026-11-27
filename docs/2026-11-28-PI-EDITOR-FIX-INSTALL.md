# Pi 4B: the shell with the Editor fix (28 November)

Kind: delivery record. Branch `pi-editor-fix`. Follows
[2026-11-28-PI-DROP-PARK-HOTFIX.md](2026-11-28-PI-DROP-PARK-HOTFIX.md) and
[2026-11-28-QSYS-ACTOR-COMPARISONS.md](2026-11-28-QSYS-ACTOR-COMPARISONS.md).

Only the shell moved. It is the same build as the drop-park hotfix (`qos-guishell` `29ddd45`,
SDK 0.6.1 with the runtime fix), with `modules/programs/mods/qsys.fpr` carrying the actor-handle
comparison fix (qos `38b83a1`).

| File | Before | After |
|---|---|---|
| `/usr/share/qosp/app.qa` | `72d216fe…` | `c5e9897f…` |
| `/usr/bin/qosp` | `46b9f0f1…` | unchanged |

**Rollback:** run `/var/lib/qosp/deployment-pi-editor-fix-19700101T073019Z/rollback.sh` (it
restores the drop-park hotfix shell). Earlier states:
- the drop-park hotfix's rollback;
- the full image backup taken before it (`.qos/pi4/image-backups/pi4b-before-droppark-hotfix-20261127/`).

A copy of the live disk is beside that backup (`Main.disk.before-editor-fix`). It was copied while
Main ran, so treat it as a convenience copy.

## Checks

| Check | Result |
|---|---|
| Staged hash | matches before install |
| Install, rolled back on any failure | "hosting QOS Main GUI Shell (4 harts, abi v24)", the six plugins published, "Main Profile ready", no panic or ABI mismatch |
| Idle after 30 s | all seven threads sleeping; RSS 63.8 MB |
| Restart | ready again, no panic |
| Fresh SSH | installed hashes match |
| The same shell on the Mac | the Editor opens on a fresh disk, takes typing, and the shell stays idle |

Not checked: the Editor opened on the Pi itself. There is no input injection on the device, so
the owner's own use is the remaining test.
