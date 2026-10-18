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
| 2026-10-02 | [ZERO-BASED.md](2026-10-02-ZERO-BASED.md) | QOS moved to 0-based positions with FP-RISC: QAR extents, coreutil, slice helpers, -1 for not found; five pins re-committed |
| 2026-10-02 | [QOS-AUDIT.md](2026-10-02-QOS-AUDIT.md) | Audit against the reference-OS ideal at b8821e6: what the September 30 to October 2 batches fixed, what contracts are still missing, eight findings, convergence order |
| 2026-10-02 | [AUDIT-FIXES.md](2026-10-02-AUDIT-FIXES.md) | The audit findings table closed: net TX parks, Portable launched images end with their pid, checked sends on the native plane, a bounded console, the scheduler model page; compiler re-pinned |
| 2026-10-02 | [ENDPOINTS.md](2026-10-02-ENDPOINTS.md) | The endpoint contract: open at the namespace, read/write/close with the owner directly, close as cancellation, refusal and death as messages, a listing as a read of "<prefix>/"; services claim their urls (no router, no vfs table); Sys.pidOf |
| 2026-10-02 | [GRAPHICS-SERVICE.md](2026-10-02-GRAPHICS-SERVICE.md) | Graphics.qa owns the display: programs are sessions keyed by pid, the focused one is drawn and gets the input, close/death/restart handled; GL.serve is the one-program case; tests/gfxshare.fpr headless |
| 2026-10-02 | [FAILURE-INJECTIONS.md](2026-10-02-FAILURE-INJECTIONS.md) | Native TX stall and killed sender, full console pipe, loaded-process storage refusal/death and routed fail-stop; legacy/modern virtio, one/two harts |
| 2026-10-02 | [SHARED-APPLICATIONS.md](2026-10-02-SHARED-APPLICATIONS.md) | Real Terra II + dungeon on one GL service, focused input and restart; system-owned Files, Terra/POS migration, two-boot refusal coverage and remaining ownership work |
| 2026-10-02 | [RELOCATABLE-APP.md](2026-10-02-RELOCATABLE-APP.md) | The Portable app image is linked at 0 with a relocation list and placed wherever the arena was reserved; the fixed slot and the macOS re-exec are gone; two load shapes of .qa, not three |
| 2026-10-03 | [MEMORY-ADMISSION.md](2026-10-03-MEMORY-ADMISSION.md) | Shared-plane fixed-heap admission, transactional refusal/cancellation, native runtime ABI compatibility, latest vector runtime integration and fresh baseline evidence |
| 2026-10-03 | [RESOURCE-ACCOUNTS.md](2026-10-03-RESOURCE-ACCOUNTS.md) | Draft resource accounts, hierarchical budgets, live configuration and optional common currency for memory, stack, messages, compute and I/O |
| 2026-10-03 | [GUI-SHELL.md](2026-10-03-GUI-SHELL.md) | Main Profile paged graphical shell, onboard appkit .qa discovery, pointer/keyboard input, boot-image wiring and prototype boundaries |
| 2026-10-03 | [PREEXISTING-FAILURES.md](2026-10-03-PREEXISTING-FAILURES.md) | Five check-all failures fixed: a log sink re-entering itself (panic record hang), RELOC/IMPORT now covered by LOAD's relsha (apps and plugins, checked before placement), Sol spawnHeap, mlpipe's Numeric, the dedup ratchet |
| 2026-10-03 | [NATIVE-INTEGRITY.md](2026-10-03-NATIVE-INTEGRITY.md) | ABI-2 SDK repin, signed recursion integration, native IMAGE/RELOC/IMPORT integrity gates and failure injections before image allocation |
| 2026-10-04 | [MVU-RELOAD.md](2026-10-04-MVU-RELOAD.md) | First object-level MVU reload integration, real plugins with scoped baseline checks, failure paths and remaining certification/replay work |
| 2026-10-04 | [VIRTIO-POLICY.md](2026-10-04-VIRTIO-POLICY.md) | Shared raw RV64 virtio initialization, exact block deadline policy and differential/failure-path verification |
| 2026-10-08 | fprisc [2026-10-08-PLANE-TABLES.md](../../fprisc/docs/2026-10-08-PLANE-TABLES.md) | The plane table split in two (actors, memory), carried by the boot block, their versions stamped in LOAD (`planeactors`, `planememory`) and refused before placement; native ABI 5; `tests/mailboxproc.fpr` + `tools/mailbox-process-check.sh`: the Base mailbox contract holds for a loaded process |
| 2026-10-08 | [STATES.md](2026-10-08-STATES.md) | Living register of intermediate states, the QOS half of fprisc's. Entry 1 one Files request end to end: client, Files owner, Qlog, block owner, worker and relay, the device claim (IDLE/HELD/ORPHAN/RECLAIMING/RESETTING/OFFLINE) and Portable's worker; the fail-stop chain, U1-U8, known gaps (three waits without a deadline, a serial owner, Ok is not durable). Entry 2 (2026-10-09) a process image: published, read, checked, granted, placed, entered, running, failing, ended, lingering, freed; grants outlive a failed launch, `error` in a process halts the machine (unverified), no budget on a process |
| 2026-10-10 | [PORTABLE-RELIABILITY.md](2026-10-10-PORTABLE-RELIABILITY.md) | Portable storage, bounded shutdown and supervision: flush acknowledgements, Qlog v3 recovery and appliance lifecycle |
| 2026-10-10 | fprisc [2026-10-10-UNIFORM-LOADING.md](../../fprisc/docs/2026-10-10-UNIFORM-LOADING.md) | Direction: one `.qa` loaded by one primitive set and one supervisor actor (`Load`, `Run`, `Unload`, monitors, budget); System.qa and Loader.qa as compositions over URLs; what this deletes in QOS (the two placers, `loadMode`, the IMPORT refusal, the boot block, the plugin path) and the two prerequisites |
| 2026-10-10 | [POWERCUT-QEMU.md](2026-10-10-POWERCUT-QEMU.md) | The appliance image cut and restarted on QEMU: `tests/powercut.fpr` + `tools/buildroot/powercut-check.py`; 20 cuts (machine and in-guest) with flushes honored and ignored, no acknowledged record lost, every log contiguous; the default 8 MiB disk fills in minutes with no retention path; an application without `Sys.ready` bricks the box; what a QEMU cut does and does not prove |
| 2026-10-11 | [BUILTIN-KERNEL.md](2026-10-11-BUILTIN-KERNEL.md) | Proposal: a builtin-only, multi-board QOS as an exokernel of actors; a small substrate (actors, mailboxes with per-actor overflow policies, non-blocking send, trap-to-message) and OS services that each own one resource; BSPs and board manifests; one message ABI for `riscv32-qos`/`riscv64-qos`; phases and fprisc prerequisites |
| 2026-10-11 | [APP-IMAGES-AS-URLS.md](2026-10-11-APP-IMAGES-AS-URLS.md) | First uniform-loading step: `/apps/<id>.qa` serves image bytes on Native and Portable through the shared `mods/appsep.fpr`; Native's launcher reads images by URL; what is not changed yet |
| 2026-10-12 | [STAR64-BUILDROOT.md](2026-10-12-STAR64-BUILDROOT.md) | First STAR64 Linux image: pinned vendor board support, modern Buildroot userspace, RV64 QEMU boot and software EGL checks; physical board validation pending |
| 2026-10-12 | [STAR64-FIRST-BOOT.md](2026-10-12-STAR64-FIRST-BOOT.md) | Public-key SSH and HDMI text login; authenticated SSH and USB keyboard console-login checks on the rebuilt RV64 image |
| 2026-10-12 | [STAR64-BOOT-DIAGNOSIS.md](2026-10-12-STAR64-BOOT-DIAGNOSIS.md) | Physical boot failure investigation: missing SD boot target fixed, firmware video error made nonfatal, rebuilt image and QEMU validation |
| 2026-10-13 | [STAR64-HARDWARE-BOOT.md](2026-10-13-STAR64-HARDWARE-BOOT.md) | Working UGREEN reader and microSD Express card; physical STAR64 boot, HDMI login, gigabit Ethernet, authenticated SSH and software EGL verified |
| 2026-10-13 | [STAR64-RUNTIME-TESTS.md](2026-10-13-STAR64-RUNTIME-TESTS.md) | Physical native C/C++, RAM, files, networking and EGL checks; 27 experimental FP-RISC Linux RV64 runs and measured memory usage |
| 2026-10-14 | [STAR64-PORTABLE.md](2026-10-14-STAR64-PORTABLE.md) | Linux RV64 compiler/runtime support and QOS Portable Main on the physical STAR64: cross-builds, plugins, storage, software EGL, HDMI and installed service |
| 2026-10-14 | [STAR64-POWERVR.md](2026-10-14-STAR64-POWERVR.md) | Matching GPU firmware and private vendor Mesa enable hardware EGL/GLES 3.2 on the installed STAR64; physical pixel, QOS shader and Main replay checks |
| 2026-10-14 | [STAR64-WIFI.md](2026-10-14-STAR64-WIFI.md) | Private local Wi-Fi provisioning, router DHCP and SSH verified with Ethernet disabled; existing wireless startup service reconnects |
| 2026-10-14 | [PI-BOOT-SPLASH.md](2026-10-14-PI-BOOT-SPLASH.md) | Pi-only vector splash, quiet HDMI boot, KMS handoff, recovery console and validation boundaries |
| 2026-10-14 | [PI-BOOT-TIMING.md](2026-10-14-PI-BOOT-TIMING.md) | Nonblocking DHCP and SD-first EEPROM boot; physical QOS readiness improves from 20.0 to 8.2 seconds; optional driver and service audit |
| 2026-10-14 | [RECURSIVE-MVU-SHELL.md](2026-10-14-RECURSIVE-MVU-SHELL.md) | Recursive MVU and explicit message/effect contracts; first Files/Logs pane migration, visible retry, persistent reader ownership, host GL and isolated Pi validation |
| 2026-10-14 | [RESPONSIVE-MVU-INPUT.md](2026-10-14-RESPONSIVE-MVU-INPUT.md) | Viewport-derived shell/app geometry, explicit focus/capture, keyboard, wheel and primary touch input; host GL and isolated Pi acceptance |
| 2026-10-14 | [GUI-PERFORMANCE.md](2026-10-14-GUI-PERFORMANCE.md) | Correlated MVU input/frame timing, temporary CPU policy, receive-root leak regression and physical Pi memory profiling |

| 2026-10-14 | [PI-MAIN-DEPLOYMENT.md](2026-10-14-PI-MAIN-DEPLOYMENT.md) | Matching production Main/app deployment, preserved disk history, KMS captures, remote interaction acceptance and rollback |
| 2026-10-15 | [GUI-IDLE-CPU.md](2026-10-15-GUI-IDLE-CPU.md) | Retained MVU frames, real worker wakeups and physical Pi idle CPU validation |
| 2026-10-15 | [STAR64-BOOT-TIMING.md](2026-10-15-STAR64-BOOT-TIMING.md) | Nonblocking networking, physical boot times and RISC-V module loader delay |
| 2026-10-15 | [STAR64-LOADER-FIX.md](2026-10-15-STAR64-LOADER-FIX.md) | Vendor-kernel RISC-V loader backports, sanitizer/QEMU checks and physical Wi-Fi boot improvement |
| 2026-10-16 | [STAR64-FPRISC-UPGRADE.md](2026-10-16-STAR64-FPRISC-UPGRADE.md) | Current FP-RISC with retained rendering, matching Portable v20 bundle, physical RV64 tests, preserved disk and reboot acceptance |
| 2026-10-16 | [FPRISC-CLIENT-STATE-REPIN.md](2026-10-16-FPRISC-CLIENT-STATE-REPIN.md) | FP-RISC 1d4309b: the frozen std/actor trusted (QOS builds again), deaths carry their reason, liveboard and uiapp on std/ui with typed client state; then 9699dbd: the five check-all legs red since 573cfd3 green |
| 2026-10-16 | [MAIN-SHELL-APPS.md](2026-10-16-MAIN-SHELL-APPS.md) | Main Profile apps: a Terminal archive with qsh, a small pipeline language over the URL namespace (ls, cat, write, append, mkdir, rm, ps, logs, let/$var); Files browsing the namespace as directories; a Clock stopwatch; Logs severity legend and pause; the file manager able to delete; a typed space reaching apps |
| 2026-10-16 | [EDITOR.md](2026-10-16-EDITOR.md) | Editor: a minimalist text editor (find, undo, session recovery, safe saves) that builds and runs FP-RISC through the host compiler; the compile bridge worker-backed so it holds no hart (ABI v21); a run's console captured per process; files remembered across boots by an index; Tab inside an app is the app's |
| 2026-10-17 | [PROGRAMS.md](2026-10-17-PROGRAMS.md) | Programs the Editor runs: confined (a memory budget of a quarter of the machine, devices and the system refused, a stop ends every actor; fprisc 2026-10-17 confined processes, ABI v22 `Sys.memTotal`); apps in the Elm shape over `std/hosted` (effects as data, typed results, keys as values, files under /home asked of the Editor), refinement- and linearity-typed Run; live checks with gutter marks and a package cache in fprd; the namespace authorization finding |
| 2026-10-18 | [WORKERS-DEPLOYMENT.md](2026-10-18-WORKERS-DEPLOYMENT.md) | Private-worker compiler repin, matching codegen-49 Pi/STAR64 bundles, native Pi Editor SDK, preserved disk history and physical acceptance |
