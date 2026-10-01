# docs/: a chronological record

Kind: index. Organized 2026-09-29 to match the FP-RISC documentation layout.
Prose pages use `YYYY-MM-DD-NAME.md` or `.txt`. Dates are approximate provenance,
usually the first-added Git date, not a claim that the entire current text existed
on that day. Each page records its last source update before this reorganization.
The August review uses its stated date; the archived README uses its split date.
Imported history can have non-monotonic commit dates, as noted in DISK.

Older accounts remain historical. Later pages may supersede them on the same
subject, but neither a filename nor a newer timestamp proves current behavior.
Specifications, proposals, measurements and working notes have different authority.
Use current source and fresh checks when deciding what works today.

## Adding and updating pages

Use today's date for a new page, identify its kind and applicable revision near
the top, and add it to the chronological table. Keep its filename when editing;
label later updates with their own dates. Substantial later records should become
new dated pages with links in both directions. Preserve old claims as history
rather than silently rewriting them into a current specification.

The Terra II additions of September 6 and 7 and image measurements added September
22 have been extracted into follow-up pages. Original section headings remain as
links so their anchors continue to lead to the moved material.

## Living references

- [Bounds](2026-09-19-BOUNDS.md): the host/loader limit register, with dated fixes.
- [HAL](2026-09-19-HAL.md): ownership and implementation backings.
- [Archive format](2026-07-19-QA-FORMAT.md): format reference; identify revisions
  explicitly when changing the contract.

A living reference keeps its original filename and dates later changes. Other
pages, including installation/versioning accounts, may describe older packaging
or semantics and are not automatically current because they remain indexed.

## Historical artifacts

`SPLIT-MANIFEST.json` and `history/monorepo-release.yml` retain their stable paths
and original contents as machine-readable split/archive evidence. They are not
active documentation pages or workflows. The dated README under `history/` is
an archived snapshot; its original monorepo-relative links are historical paths.
The embedded historical help text in `programs/mods/docsdata.fpr` also retains
its original paths: editing those string values would change a module identity.
Source-adjacent READMEs under `tools/` stay beside the tools they explain.

## Pages

| date | page | what it is |
|---|---|---|
| 2026-07-19 | [QA-FORMAT.md](2026-07-19-QA-FORMAT.md) | QAR2 application archive and loader contract |
| 2026-08-25 | [NOTES.txt](2026-08-25-NOTES.txt) | Unreconciled ideas, commands and implementation notes |
| 2026-08-25 | [VERSIONING.md](2026-08-25-VERSIONING.md) | Module commits, stores, locks and releases |
| 2026-08-26 | [DISK.txt](2026-08-26-DISK.txt) | Disk partitions and the QLOG v2 format |
| 2026-08-26 | [SCHEDULER.txt](2026-08-26-SCHEDULER.txt) | Scheduling, timers, parked sleep and admission fixes |
| 2026-08-29 | [FPR-QOS-REVIEW.md](2026-08-29-FPR-QOS-REVIEW.md) | FP-RISC, Sol and QOS review at revision 614a9e9 |
| 2026-09-02 | [FPRLIVE.md](2026-09-02-FPRLIVE.md) | Websocket MVU sessions, load results and limits |
| 2026-09-02 | [VERIFICATION.md](2026-09-02-VERIFICATION.md) | C verification options and three historical probes |
| 2026-09-04 | [MESHES.md](2026-09-04-MESHES.md) | Application-provided meshes and scene text |
| 2026-09-04 | [SOUND.md](2026-09-04-SOUND.md) | Procedural audio and the MP3 music channel |
| 2026-09-04 | [TERRA2-V1.md](2026-09-04-TERRA2-V1.md) | Terra II V1 rules and scope |
| 2026-09-04 | [TERRA2.md](2026-09-04-TERRA2.md) | Terra II baseline, controls and verification |
| 2026-09-05 | [UI2D.md](2026-09-05-UI2D.md) | 2D scene layer, text and clipping |
| 2026-09-06 | [TERRA2-POLISH.md](2026-09-06-TERRA2-POLISH.md) | Terra II: polish and art pass |
| 2026-09-07 | [POS1-DESIGN.md](2026-09-07-POS1-DESIGN.md) | POS v1 model, persistence and multi-register design |
| 2026-09-07 | [POS1.md](2026-09-07-POS1.md) | POS v1 on QOS and its verification |
| 2026-09-07 | [TERRA2-LIFECYCLE.md](2026-09-07-TERRA2-LIFECYCLE.md) | Terra II: lifecycle, persistence, cards and terminal |
| 2026-09-08 | [DUNGEON.md](2026-09-08-DUNGEON.md) | Dungeon game as a pure MVU program |
| 2026-09-10 | [INSTALL.md](2026-09-10-INSTALL.md) | Toolchain installation and workspace layout; historical packaging context |
| 2026-09-18 | [REPOSITORY-SPLIT.md](2026-09-18-REPOSITORY-SPLIT.md) | Repository ownership, dependency and release split |
| 2026-09-18 | [MONOREPO-README.md](history/2026-09-18-MONOREPO-README.md) | Combined README preserved at the repository split |
| 2026-09-19 | [BOUNDS.md](2026-09-19-BOUNDS.md) | Host, loader and memory-layout bounds |
| 2026-09-19 | [HAL.md](2026-09-19-HAL.md) | QOS HAL ownership and host/virt backings |
| 2026-09-19 | [INPUT.md](2026-09-19-INPUT.md) | Portable input from terminals and evdev |
| 2026-09-21 | [IMAGE.md](2026-09-21-IMAGE.md) | Bootable QOS Portable with Buildroot |
| 2026-09-22 | [IMAGE-MEASUREMENTS.md](2026-09-22-IMAGE-MEASUREMENTS.md) | QOS Portable image: memory and speed measurements |
| 2026-09-29 | [QOS-ARCHITECTURE-AUDIT.md](2026-09-29-QOS-ARCHITECTURE-AUDIT.md) | Source audit against the minimalist actor OS ideal, with selected Portable checks; September 30 memory/image-slot and C migration follow-ups |
| 2026-09-30 | [FAILURE-HONESTY.md](2026-09-30-FAILURE-HONESTY.md) | The audit's first step: RPC refusal/death/correlation, honest `fileWr` and loader persistence, the native slot guard and root-exit quiescence |
| 2026-10-01 | [LAUNCHER-IDLE.md](2026-10-01-LAUNCHER-IDLE.md) | The native launcher leaked while idle: an arena around the wait, and a 1 ms park |
| 2026-10-01 | [QOS-BASELINE.md](2026-10-01-QOS-BASELINE.md) | Fixed actor-runtime pin, explicit LiveView safety, graphics-independent compile and dynamic-slot failure gates |
| 2026-10-01 | [DISK-SUSPENSION.md](2026-10-01-DISK-SUSPENSION.md) | Native actor-parked completion, Portable copied worker requests, cancellation cleanup and single-hart progress regression |
| 2026-10-01 | [DISK-HARDENING.md](2026-10-01-DISK-HARDENING.md) | Disk deadlines, stalled-device reset, offline and overload refusal; device failures fail-stop the caller instead of halting the machine |
| 2026-10-01 | [DISPLAY-BUFFERS.md](2026-10-01-DISPLAY-BUFFERS.md) | The display in O(1) memory: front and back buffers as two halves of one linear Vector, the launcher a `Sys.loopWith` (it leaked ~236 KB per redraw) |
| 2026-10-01 | [PROCESS-IMAGES.md](2026-10-01-PROCESS-IMAGES.md) | Native process images are buddy blocks: linked at 0 with a RELOC list, any number at once, freed when their pid ends; data statics copied out of a dying image, functions refused; no slot |
| 2026-10-01 | [IMPORT-TABLE.md](2026-10-01-IMPORT-TABLE.md) | Portable plugins are relocatable and bind the app's runtime by name (stubs through slots, an export table); no PLUGSLOT, plugsyms, shell stamps or plugin window |

- 2026-10-01: [CODE-PUBLICATION.md](2026-10-01-CODE-PUBLICATION.md) — Native loaded code is fenced on every hart before actor dispatch.
- 2026-10-01: [TYPED-VECTORS.md](2026-10-01-TYPED-VECTORS.md) — Element-typed buffers, updated TUI module and Portable A64/Native RV64 regression gate.
