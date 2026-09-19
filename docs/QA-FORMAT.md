# QA-FORMAT.md — the .qa app archive, revision QAR2

A `.qa` is the unit of app distribution and loading on both QOS
Portable and QOS Native.  QAR2 removes ELF from the archive: the ELF
that the toolchain links is consumed ONCE, at build time, by
`tools/mkqa.py`, which extracts the loadable bytes into a flat image.
What ships is a container a loader can consume with one copy, one
zero-fill, and one protection flip — no header chasing, no program-
header walking, no format written by someone else's linker.

The host binaries (qosp, the native kernel) remain ordinary build
products of their platforms; QAR2 governs only what THEY load.

## Container

    QAR2\n
    MANIFEST <off> <len>\n
    LOAD <off> <len>\n
    IMAGE <off> <len>\n
    \n
    <payloads>

Same table discipline as QAR1: `NAME OFFSET LENGTH` lines, offsets
relative to the first payload byte (the byte after the blank line),
unknown sections ignored by design.  Everything before the payloads is
text — `xxd` a .qa and read it.

## MANIFEST

Unchanged from QAR1: the minimal-TOML subset (`name`, `id`,
`loadMode`, `[permissions.required]`, `[permissions.optional]`).

## LOAD — the entire loader contract, as text

    base <decimal>\n         where the image was linked (absolute)
    entry <decimal>\n        entry point, as an OFFSET from base
    execsz <decimal>\n       bytes of the r-x prefix (text + rodata)
    rwoff <decimal>\n        offset of the first writable byte
    imagesz <decimal>\n      bytes of IMAGE to copy to base
    memsz <decimal>\n        total span; [imagesz..memsz) is zero-filled
    sha <64 hex>\n           sha256 of the IMAGE bytes (optional line)

Decimal, line-oriented, order-insensitive — parseable by the same
string-walking code system.fpr already uses for the section table.
`entry` is an offset, never an absolute address: an archive states
where it goes and where it starts relative to that, nothing else.

The linker script's ALIGN(0x10000) between the r-x and rw segments is
what makes `execsz`/`rwoff` honest: a loader may round `execsz` up to
its page size and must refuse if that round-up reaches `rwoff` (the
W^X boundary check, previously derived by walking PT_LOAD flags).

## IMAGE

The flat memory image: every PT_LOAD's file bytes laid out at
(vaddr - base), gaps zero-filled at build time.  Loading is:

    check   base/memsz inside the window, execsz page-round < rwoff
    copy    IMAGE -> base            (imagesz bytes)
    zero    [base+imagesz .. base+memsz)
    verify  sha, if the host can (qosp does; bare metal may skip)
    protect r-x over the execsz prefix (hosts with mprotect)
    enter   base + entry

That is `loader/qaimg.c` in its entirety, shared by qosp's slot
loader, qosp's plugin loader, and the native kernel's process loader
(`Sys.loadImageAt`).  `elfload.c` is retired from every load path.

## Placeholders

`mkqa.py <manifest> - -o out.qa` (no ELF) emits a LOAD of all zeros
and an empty IMAGE — the name-dispatch era's placeholder apps keep
working; a loader sees `memsz 0` and knows there is nothing to load.

## Why not ELF

The loaders used none of ELF's machinery — no relocation, no dynamic
linking, no symbols at load time.  What they consumed was "two byte
ranges, an entry, and a W^X boundary", reconstructed each load by
parsing headers written for a different purpose.  QAR2 states those
five numbers directly, so the archive parses with the tokenizer the
system already owns, and the failure modes are named refusals
("image outside the window", "execsz reaches rwoff", "sha mismatch")
instead of malformed-header surprises.
