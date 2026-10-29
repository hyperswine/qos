# Installed Main disk creation and offline app installation

Date: 2026-10-29. Slice 2 of the
[Portable app workflow](2026-10-28-PORTABLE-APP-WORKFLOW.md).

The installed AArch64 desktop SDK now supports the complete local disk loop:

```sh
qos new my-counter
cd my-counter
fpr build --target=qos-portable
qos disk create qosp.disk --profile main --size 32
qos install build/my-counter.qa qosp.disk
qos run qosp.disk
```

Create the disk once. Later builds and installs reuse it. `--size` is MiB;
creation refuses an existing path. The SDK ships matching prebuilt Main and
onboard archives, not a copy of a mutable user disk. `disk create` generates a
new durable QLOG v3 disk from those archives and stores its Main compatibility
record at `qos/profile`. It does not reset or reconstruct an existing disk.

`install` reads identity, title and version from the archive manifest. The
filename is irrelevant. A new ID is appended to `apps/index` once; replacing
that ID changes `apps/<id>.qa` without adding a second catalogue entry. The
installer preserves previous records and app history byte for byte. It checks
capacity before writing and refuses a full DATA partition with a compact-or-
create-larger-disk message. It does not compact or reclaim user history itself.

`run` validates the disk and all catalogue archives, then launches the matching
prebuilt graphical host and Main. No compiler or source checkout is needed to
run an existing disk. The counter is still session-local; persistent app state
is the next slice. Installing a replacement preserves existing user records,
but SDK v1 does not yet provide a public per-app store.

## Disk ownership

All Portable block-tier owners and the offline installer acquire a nonblocking
exclusive `flock` on the disk inode before reading/modifying disk state. The
lock covers symlink/hard-link aliases and remains held for the owner's lifetime.
The tools never replace a live disk inode. File replacement by an unrelated
administrator/tool is outside this cooperative protocol.

`qos run` acquires the lock before validating. It passes that exact open-file
description to the child host. The host verifies the inode, duplicates it with
close-on-exec, and removes the handoff environment variable. There is no
unlock/reopen gap between validation and launch. A second host or installer
refuses the busy disk. The raw block tier also takes this lock when qosp is
launched directly. With an explicit `FPR_DISK`, the host refuses launch if that
disk cannot be acquired instead of silently continuing without it.

Prebuilt hosts expose `--sdk-info` for ABI/lock capability checks. Staging refuses
old or mismatched binaries rather than claiming the new lock contract for them.
The installed SDK hashes its host/profile files and checks them before launch.

## Compatibility and archive checks

The packager records architecture from ELF's machine field and refuses a
contradictory declared architecture. Installation checks QAR2 section boundaries,
unique sections, LOAD bounds/integer range, IMAGE and relocation/import hashes,
relocation/import offsets and object shapes. It also reads the native module
table to require exactly one root `appMain` export with one actor argument.

External desktop archives must carry matching architecture, Portable/codegen
ABI, desktop API and session metadata. Legacy onboard plugins may omit the
session/API metadata only when their exact archive hash matches this SDK's
profile. Architecture is required for every image. Rebuild older archives with
the matching SDK when refused. The native code remains cooperative trusted
code; these checks detect malformed images and declared incompatibility.

A disk's profile record must match the selected SDK's OS, architecture, ABI,
desktop API and session. Missing or incompatible profiles are refused before
writes. The new installer does not infer these contracts for legacy or pending-
recovery disks; keep using their existing QOS recovery/migration tools first.

## One publication boundary

The archive and complete updated catalogue are packed into one existing QLOG
`QBLK` record. Installation follows QLOG's existing v3 append discipline:

1. Scan and verify the committed log, select the newest valid stable superblock,
   validate compatibility, and check DATA capacity and generation room.
2. Write the complete bulk record into uncommitted DATA after the old head.
3. Flush DATA (`fsync`, plus `F_FULLFSYNC` on macOS).
4. Publish one new-generation checksummed superblock in the alternate slot.
5. Flush metadata before reporting success.

The previous committed pages and other superblock remain intact. A torn staged
write cannot be discovered through the old head; a torn superblock falls back
to the previous valid slot. Recovery sees the complete old version or complete
new version, including its catalogue, never a partially installed app.

Before publication an interruption leaves the previous version installed.
After publication the complete new version can be visible even if the caller
was killed before receiving success. A flush/I/O error around that point can
therefore have an uncertain acknowledgement; reopening/validating the disk
establishes its committed version. Do not interpret a missing success response
as a guarantee that the old version remains. This is the normal atomic commit
boundary, not a promise to undo an already committed update after process death.

## Contributor CLI migration

The old toolchain installer is now explicit:

```sh
./qos.py toolchain install --prefix /tmp/qos-source-toolchain
# --full retains compiler/platform sources and contributor tests
```

`qos install --prefix ...` refuses with that migration hint. CI, the legacy
Homebrew formula and standalone SDK smoke callers use the new spelling. The
standalone `new --template min|service|mvu|notes`, `run SOURCE`, `pack` and moved
bundle workflows remain available from that toolchain. Its disk fixture command
is `qos.py disk seed IMAGE SIZE QA...`; the old `disk IMAGE SIZE QA...` spelling
also remains accepted.

For contributor access to desktop commands, set `QOS_PORTABLE_SDK` to a staged
prefix, then use `qos.py disk create`, `qos.py install`, and `qos.py run FILE.disk`.
The installed desktop CLI itself requires no source-tree environment variables.

## Verification

Run the focused disk policy/fault tests and real C/Python lock interoperation:

```sh
python3 -m unittest discover -s tests -p 'test_desktop_install.py'
python3 tools/desktop-lock-check.py
sh qos/tests-host/blkraw-check.sh
python3 tools/portable-durable-check.py
```

The tests cover new app and replacement publication, process death during DATA
and metadata stages, torn superblocks, data/commit sync errors, invalid archive
spans/entry/ABI/architecture/session, full and busy disks, aliases, duplicate or
missing catalogue records, tombstones, long bulk keys, and preservation of
unrelated history. The production FP-RISC QLOG reader separately reads the
Python-created bulk records in the installed acceptance test.

The installed acceptance runner now exercises disk creation, installation and
replacement through the actual CLI, compares unrelated app/user record hashes,
opens the updated counter in graphical Main, refuses an install while Main owns
the disk, then exits with storage drained. Checkout and GHC/Cabal access are
blocked and SDK files are read-only throughout:

```sh
python3 tools/portable-sdk-check.py --sdk /tmp/qos-sdk \
  --driver /tmp/sdk-driver.qa --output /tmp/qos-acceptance --gui
```

These are process, format and runtime tests. Physical power cuts, SD-card
qualification, and Linux/x86-64 installed runtime acceptance are separate work.

The 2026-10-29 macOS AArch64 milestone passed these checks. Final captures
showed the changed **Counter Updated** code and Count 0 then Count 1. Other
app archives and seeded user records remained unchanged through replacement
and Main launch. See the [evidence summary](evidence/2026-10-29-desktop-disk-install.json).
