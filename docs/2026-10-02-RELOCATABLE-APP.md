# The Portable app image is relocatable: one load path, no address in an app

Date: 2026-10-02. Kind: implementation record. Convergence item 6 of
[2026-10-02-QOS-AUDIT.md](2026-10-02-QOS-AUDIT.md). QOS revision: the
commit carrying this page. Source: `qos-app.mk`, `qos/appside/link-qosapp*.ld`,
`qos/portable/host.c`, `qos/portable/qosp.fpr`.

## Before

A QOS Portable application image was linked at `QOS_SLOT_BASE`, a fixed
virtual address (1 TiB on macOS, 16 GiB elsewhere), and the host had to
reserve its arena exactly there. When the host's own ASLR slide happened
to land on that address, the host re-executed itself up to eight times
hoping for a different slide, and failed with "the app image is linked
there, so there is no fallback". Plugins and native process images had
already become relocatable ([2026-10-01-IMPORT-TABLE.md](2026-10-01-IMPORT-TABLE.md),
[2026-10-01-PROCESS-IMAGES.md](2026-10-01-PROCESS-IMAGES.md)); the app
image was the last fixed one, and the `.qa` container had three load
shapes.

## Now

The app is linked at 0 with `--emit-relocs`, the same way a plugin is,
and `mkqa` writes its RELOC list and verifies it against a second link
256 MiB higher (`--check-moved`). The host reserves the arena at the
published address when it is free, and anywhere else when it is not;
`Host.loadImage` takes the RELOC section, places the image at the
arena's start, moves its address words there, and publishes its code
r-x. Nothing in an app depends on where it lands: the entry reads the
arena from the boot record, the export table names its symbols, and
plugins bind by name. The re-exec is gone. A fixed image (`base` not 0)
is refused unless the arena happens to be where it was linked, so an
archive built before this change says so by name.

The `.qa` container now has two load shapes, not three: a relocatable
image with or without an IMPORT section. The fixed-slot form is
history.

## Verification

`QOSP_ARENA_ANYWHERE=1` makes the host skip the published address on
purpose, so the image is placed and relocated wherever the OS put the
arena. The Portable legs run both ways; the plugin-import, apps,
pathnotes and graphics legs were run relocated. The fault handler's
"inside the image" test uses the placed image's bounds.

Found on the way: the export table symbol was declared weak so that the
first of the two links could leave it undefined, and a weak extern is
reached through the GOT, whose slot no relocation list moves; `mkqa`
refused the image by name (`R_AARCH64_ADR_GOT_PAGE`). It is a strong
symbol now and the first link ignores unresolved symbols explicitly.
