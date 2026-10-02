# Shared applications and system-owned Files

Kind: implementation and verification record. QOS working changes based on
`d2e8c69`, FP-RISC `bca7278d60b22de7fab78b2f9111cc8a712c91b6`.

The compiler pin was refreshed with `./qos.py fprisc --pin`. It already named
this latest clean local revision, so the lock bytes did not change. At verification,
local FP-RISC was two commits ahead of fetched origin/main.

## Application composition

`programs/mods/services.fpr` creates a Portable system composition root. It
opens the disk once, starts one QLog owner behind `programs/mods/files.fpr`,
and registers namespace endpoints. Adding graphics starts one Graphics actor
with the real GL backend. `launch` creates distinct application pids, installs
their grants, then wakes them. Application adapters inherit their application pid.

Terra II and dungeon expose `run hub tag app`. Both attach a graphics session,
use the existing MVU engine, and close the session on orderly exit. Terra II and
POS use `FS.connect` instead of opening a raw block device. This small client
adapter preserves their existing storage API while sending operations through
the namespace. Terra II no longer compacts the shared disk on startup.

Files URLs are `/services/files/<record>/{latest,replay,stats,append,delete}`.
Status is readable at `/services/files/status`; global compaction is restricted
to system pid 0. Application grants cover record prefixes. These are cooperative
actor and namespace boundaries, not native memory isolation or a security sandbox.

The latest checker also exposed a pre-existing non-exhaustive `connFrame`
integer discriminator in FPRLive. An unexpected status now closes with protocol
error 1002. POS compilation is included in the baseline compile gates.

## Fresh verification

- `python3 tools/gfxapps-check.py --output /tmp/qos-gfxapps-final2` passed on
  macOS Apple M4, OpenGL 4.1 Metal through GLFW, one hart. The real Terra II and
  dungeon update/subscription/view code ran as separate application pids on one
  graphics service. Focused evdev FIFO keyboard input changed each game's frame;
  Terra II closed while dungeon continued, restarted with its saved game, then
  both closed without sessions remaining. Five 960 x 600 PPM captures were checked
  for non-uniform pixels and before/after changes. Title and post-input gameplay captures were
  also visually inspected. Test wrappers add lifecycle telemetry, a quit port
  and a snapshot offset; they do not replace application scenes or rules.
- `XDG_CACHE_HOME=/tmp/qos-services-cache python3 tools/files-service-check.py`
  passed on one hart. Two distinct application pids append and read their own
  records, are refused each other's records and global compaction, and preserve
  both logs across two boots (replay lengths 6 then 12 bytes). Killing the Files
  endpoint owner produces `Err` rather than a stuck caller. The earlier single
  boot also passed on the default ten-hart host.
- `./qos.py test files graphics dungeon` passed all three selected smoke legs.
- POS built as a relocatable Portable archive. Baseline compile/refusal gates
  passed. `./qos.py lock --check` passed; its previously missing graphics actor
  pin entry was regenerated.

Both durable runners are in `check-all.sh`; Files is also in the smoke suite.
The real graphics runner opens a window on macOS or uses Xvfb on Linux. Missing
GLFW/display prerequisites produce an explicit skip in the full sweep. The full
sweep, Pi hardware, native RV64 graphics and POS websocket interactions were not
run in this increment; the current Python lacks `websockets`.

## Remaining migration

This completes the first shared-application proof and the disk ownership slice.
Clock opening is centralized, but MVU still receives the legacy mtime capability;
it is not a Clock endpoint service. Sound remains direct native calls. Network
ownership, the remaining applications, and moving substantial C policy into FPR
remain follow-up work. This Portable composition root does not yet replace the
native `system.fpr` boot composition.
