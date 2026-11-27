# Pi 4B: the Files freeze fixed by an SDK 0.6.1 runtime hotfix (28 November)

Kind: delivery record. Branch `pi-droppark-hotfix`. Follows the Files freeze the owner recorded in
[2026-11-27-PI-GUISHELL-SDK-0.6.1-INSTALL.md](2026-11-27-PI-GUISHELL-SDK-0.6.1-INSTALL.md)
("Files freeze and app reset").

## The cause

The cause was a double free in the FP-RISC runtime, not in Files or the shell. When an actor's
16-entry drop-park list was full, `fpr_drop_park` released the oldest entry before taking the new
hold. When the oldest entry was the same message slab, that slab was freed, re-parked, and freed
again at the next drain.

The double free corrupted the buddy allocator's free lists:
- **On the Pi:** a free list with a cycle made a scan spin forever under the allocator lock, and
  the other harts spun on that lock. This is the recorded freeze: three harts runnable at full CPU,
  no I/O, no fault.
- **On the desktop:** the same shell binary also crashed sometimes.

The shell triggers it when one message slab holds many roots that are released in one turn, as
when a Files listing arrives through the message port.

The investigation, and unfixed against fixed runs on the same random seeds, are in fprisc
`docs/2026-11-27-DROP-PARK-DOUBLE-FREE.md`. The fix is fprisc main `e5639cef`.

## What changed on the Pi

Only the two images that link the runtime moved. They were built from the SDK 0.6.1 pair with
the fix alone (fprisc branch `hotfix/0.6.1-drop-park`, `655fddaa` = `151b3eeb` + the fix), so
codegen (262) and the ABI (`24.262`) are unchanged:
- The six disk apps import the runtime from the host and stay as they are.
- The Editor compiler SDK stays as it is.
- qos's fprisc pin did not move.

| File | Before | After | From |
|---|---|---|---|
| `/usr/bin/qosp` (`qosp-es`, ALSA) | `0be80ff8…` | `46b9f0f1…` | qos `3d66631` + the hotfix fprisc, `qos-pi-builder:20261127` (`build.sh`) |
| `/usr/share/qosp/app.qa` | `185a9c0e…` | `72d216fe…` | `qos-guishell` `29ddd45` (it builds the old `185a9c0e…` byte for byte unpatched), `qos build` with a copy of SDK 0.6.1 whose `platform/runtime/actors.c` carries the fix |

**Rollback:** run `/var/lib/qosp/deployment-pi-droppark-hotfix-19700101T065621Z/rollback.sh`. It
restores both files and restarts Main. The Pi's clock is unset, so the directory carries a 1970
timestamp.

**Full image backup, taken first:** stored on the Mac in
`.qos/pi4/image-backups/pi4b-before-droppark-hotfix-20261127/`.
- Both system partitions (boot 32 MiB, root 512 MiB), copied with Main and fprd stopped and root
  remounted read-only. The devices' SHA-256 equals the copies'.
- `/data/qosp` as a tar (90 files, with per-file SHA-256).
- The partition table.

## Checks

| Check | Result |
|---|---|
| Staged hashes | match before install |
| Install, rolled back on any failure | Main started on the new host and shell: "hosting QOS Main GUI Shell (4 harts, abi v24)", all six plugins published, "Main Profile ready (10 shortcuts, 2 pages)", no panic or ABI mismatch |
| Idle after 45 s | all seven threads sleeping; RSS 63.8 MB |
| `qos-fprd selftest` | ok |
| Restart of Main | ready again, no panic |
| Fresh SSH | installed hashes match |
| The hotfix shell on the Mac, random-key soak under `lldb` | no fault (this setup caught the double free on the same seeds without the fix) |

Not checked: Files driven on the Pi. The device has no input injection, so the owner's own use of
Files is the remaining test.

## Also found

Opening the Editor from the desktop shell built with SDK 0.6.1 panics the whole shell
(`Int: expected Int or BigInt`, right after `creating /home/.editor/session`). The panic happens
without the hotfix too. Not investigated.
