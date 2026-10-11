# App images as URL objects: /apps/<id>.qa

Date: 2026-10-11. Kind: implementation record. The first step of fprisc's
[2026-10-10-UNIFORM-LOADING.md](../../fprisc/docs/2026-10-10-UNIFORM-LOADING.md)
("a load begins with `open` of a URL"), toward removing the plugin concept.
fprisc revision: `4f621a3` (the pinned compiler). No ABI, archive-format or
module-pin change.

## What changed

An application image is now an object in the namespace like a file or a
service. On both Native and Portable, the owner of `/apps` answers a read of
`/apps/<id>.qa` with the image's bytes, exactly as installed. It uses the
endpoint contract (`2026-10-02-ENDPOINTS.md`): open, read, close.

- **`programs/mods/appsep.fpr`** (new, shared by both platforms):
  - `images fetch describe` is the owner's reader for `EP.simple`.
  - `read me ns id` is the client: open, read, close of `qaUrl id`.
  - `imageId` accepts only `/apps/<id>.qa` with no `/` in the id.
  - Where the bytes come from is the platform's `fetch`, injected at boot.
- **Native (`programs/system.fpr`):**
  - System claims `/apps` at boot with a fetch that keeps the old order: the
    disk's `apps/<id>.qa` record wins, and the shipped rodata set
    (`Apps.read`) is the fallback.
  - The launcher's `qaFor` no longer names a storage record or `Apps.read`.
    It reads `/apps/<id>.qa` through the namespace, as its header comment
    already described.
- **Portable (`programs/mods/qsys.fpr`):**
  - The `/apps` owner keeps its descriptions of `/apps` and `/apps/<id>`, and
    now also serves `/apps/<id>.qa` from the disk's record.
  - Each loaded app's `.qa` URL is claimed, so listings show it. The
    namespace in `tests/qsys.fpr` lists 14 paths, up from 12.

## Not changed yet

- **Portable's boot enumeration** (`attachAll`) still reads `apps/index`
  and each `apps/<id>.qa` as storage records before the namespace exists.
  Moving it to "open the URL, then load" needs the namespace up before the
  attach, which is the supervisor step of the direction page.
- **The endpoint is read-only.** Installing an image by writing its URL is a
  later step.
- **`apps/index` and `sys/live`** are still storage records, not URLs.
- **The plugin path itself** (`Plug.attach`, `Sys.attachImage`, `loadMode`,
  the loader actor's four messages) is untouched.

## Verification

On this Mac, with the pinned compiler:

| Check | Outcome |
|---|---|
| `tools/qsys-check.sh` (asserts `image=QAR2` too) | two boots HOLD; `image=QAR2`, 14 paths |
| `./qos.py native --smoke` | launcher up at +0.21 s: TUIAppLauncher was read through `/apps/TUIAppLauncher.qa` |
| `tools/epproc-check.sh` | `display=ok clock=ok ungranted=not granted: /pins/1 (read) kv=ok` |
| `tools/nativeimage-check.sh` | HOLDS |
| `tools/plugimports-check.sh` | HOLDS |
| `./qos.py test` | 16 of 16 |
| `./qos.py lock --check` | 53 pins, current |
