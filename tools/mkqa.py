"""mkqa.py -- assemble a .qa (QOS App Archive, QAR2) from a manifest + ELF.

    tools/mkqa.py <manifest.toml> <app.elf> -o out.qa

QAR2 (docs/2026-07-19-QA-FORMAT.md): the ELF is consumed HERE, once, at build
time.  Its PT_LOADs are flattened into one image blob; what ships is

    QAR2\n MANIFEST/LOAD/IMAGE[/RELOC] table \n\n  payloads

A native process image is RELOCATABLE (--relocatable): linked at 0, with
a RELOC section listing the address words the loader moves by wherever
it put the block (docs/2026-10-01-PROCESS-IMAGES.md).

where LOAD is six text numbers (base, entry offset, execsz, rwoff,
imagesz, memsz) + a sha256 of the image -- the entire loader contract.
Every consumer (qosp slot, qosp plugins, the native kernel's
Sys.loadImageAt, system.fpr's parser) reads this exact byte layout.

If <app.elf> is '-' or missing, LOAD is all zeros and IMAGE is empty --
the name-dispatch placeholder mode (the running image resolves `entry`
by symbol; there is nothing to load).
"""
import sys, os, argparse, struct, hashlib

PF_X, PF_W = 1, 2
PT_LOAD = 1

def flatten_elf(elf):
    """ELF64 PT_LOADs -> (base, entry_off, execsz, rwoff, image, memsz)."""
    if elf[:4] != b"\x7fELF":
        raise SystemExit("mkqa: not an ELF image")
    if elf[4] != 2:
        raise SystemExit("mkqa: only ELF64 (the QOS app targets are all 64-bit)")
    little = elf[5] == 1
    fmt = "<" if little else ">"
    e_entry, e_phoff = struct.unpack_from(fmt + "QQ", elf, 24)
    e_phentsize, e_phnum = struct.unpack_from(fmt + "HH", elf, 54)
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, _pa, p_filesz, p_memsz, _al = \
            struct.unpack_from(fmt + "IIQQQQQQ", elf, off)
        if p_type == PT_LOAD and p_memsz:
            segs.append((p_vaddr, p_offset, p_filesz, p_memsz, p_flags))
    if not segs:
        raise SystemExit("mkqa: ELF has no PT_LOAD segments")
    segs.sort()
    base = segs[0][0]
    memsz = max(v + m for v, _o, _f, m, _fl in segs) - base
    # image extends to the last FILE byte; the bss tail past it is
    # zero-filled by the loader (memsz - imagesz)
    imagesz = max((v + f for v, _o, f, _m, _fl in segs if f), default=0) - base
    img = bytearray(imagesz)
    for v, o, f, _m, _fl in segs:
        img[v - base : v - base + f] = elf[o : o + f]
    execsz = max((v + f - base for v, _o, f, _m, fl in segs if fl & PF_X),
                 default=0)
    rwoff = min((v - base for v, _o, _f, _m, fl in segs if fl & PF_W),
                default=memsz)
    if not base <= e_entry < base + memsz:
        raise SystemExit("mkqa: e_entry outside the loadable span")
    return base, e_entry - base, execsz, rwoff, bytes(img), memsz

# Per machine: the relocation type that is an absolute 64-bit address word
# (moved by `+= d` when the image lands d above its link address), and the
# types whose effect does not depend on where the image lands -- PC-relative
# code and data references, differences of two symbols, page offsets (the
# image always moves by a multiple of 64 KiB, so an address's low 12 bits
# do not change), and linker bookkeeping.  Anything else binds the image to
# its link address and is refused.
RELOC_RULES = {
    243: ("RISC-V", 2, {     # EM_RISCV; R_RISCV_64
        0, 16, 17, 18, 19,   # NONE BRANCH JAL CALL CALL_PLT
        23, 24, 25,          # PCREL_HI20 PCREL_LO12_I PCREL_LO12_S
        33, 34, 35, 36, 37, 38, 39, 40,  # ADD8..ADD64 SUB8..SUB64
        43, 44, 45,          # ALIGN RVC_BRANCH RVC_JUMP
        51, 52, 53, 54, 55, 56, 57,      # RELAX SUB6 SET6 SET8 SET16 SET32 32_PCREL
    }),
    183: ("AArch64", 257, {  # EM_AARCH64; R_AARCH64_ABS64
        0, 260, 261, 262,    # NONE PREL64 PREL32 PREL16
        273, 274, 275, 276,  # LD_PREL_LO19 ADR_PREL_LO21 ADR_PREL_PG_HI21(_NC)
        277, 278, 284, 285, 286, 299,    # ADD/LDST*_ABS_LO12_NC: page offsets
        279, 280, 282, 283,  # TSTBR14 CONDBR19 JUMP26 CALL26
    }),
    62: ("x86-64", 1, {      # EM_X86_64; R_X86_64_64
        0, 2, 4, 24,         # NONE PC32 PLT32 PC64
    }),
}
SHT_SYMTAB, SHT_RELA = 2, 4
SHF_ALLOC = 2
SHN_UNDEF, SHN_ABS = 0, 0xFFF1

def elf_sections(elf):
    fmt = "<" if elf[5] == 1 else ">"
    e_shoff, = struct.unpack_from(fmt + "Q", elf, 40)
    e_shentsize, e_shnum = struct.unpack_from(fmt + "HH", elf, 58)
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        name, typ, flags, addr, off, size, link, info, align, entsz = \
            struct.unpack_from(fmt + "IIQQQQIIQQ", elf, o)
        secs.append((typ, flags, addr, off, size, link, info, entsz))
    return fmt, secs

def elf_symbols(elf):
    """(name, value, size, shndx, bind) for every symbol of the static symtab."""
    fmt, secs = elf_sections(elf)
    out = []
    for typ, _f, _a, off, size, link, _i, entsz in secs:
        if typ != SHT_SYMTAB:
            continue
        stroff = secs[link][3]
        for k in range(size // entsz):
            st_name, st_info, _o, st_shndx, st_value, st_size = \
                struct.unpack_from(fmt + "IBBHQQ", elf, off + k * entsz)
            end = elf.index(b"\0", stroff + st_name)
            out.append((elf[stroff + st_name:end].decode(), st_value, st_size, st_shndx, st_info >> 4))
    return out

def relocations(elf, base, imagesz):
    """The offsets (from base) of every 64-bit word that holds an absolute
    address inside the image, from an ELF linked with --emit-relocs.  Any
    other relocation that would bind the image to its link address is an
    error: such an image cannot be moved, and placing it would be wrong."""
    fmt = "<" if elf[5] == 1 else ">"
    e_machine, = struct.unpack_from(fmt + "H", elf, 18)
    if e_machine not in RELOC_RULES:
        raise SystemExit(f"mkqa: --relocatable knows no relocation rules for ELF machine {e_machine}")
    arch, abs64, free = RELOC_RULES[e_machine]
    _fmt, secs = elf_sections(elf)
    offs, refused = set(), []
    for typ, _f, _a, off, size, link, info, entsz in secs:
        if typ != SHT_RELA:
            continue
        target = secs[info]
        if not (target[1] & SHF_ALLOC):
            continue  # debug info: not loaded
        symtab = secs[link]
        for k in range(size // entsz):
            r_offset, r_info, _add = struct.unpack_from(fmt + "QQq", elf, off + k * entsz)
            rtype, rsym = r_info & 0xFFFFFFFF, r_info >> 32
            st_shndx, = struct.unpack_from(fmt + "H", elf, symtab[3] + rsym * symtab[7] + 6)
            if rtype in free:
                continue
            if st_shndx == SHN_ABS:
                continue  # an absolute constant stays put wherever the image goes
            if rtype == abs64 and st_shndx != SHN_UNDEF:
                at = r_offset - base
                if not 0 <= at <= imagesz - 8:
                    raise SystemExit(f"mkqa: an address word at 0x{r_offset:x} lies outside the image's file bytes")
                offs.add(at)
                continue
            refused.append((rtype, r_offset))
    if refused:
        kinds = ", ".join(sorted({str(t) for t, _ in refused}))
        raise SystemExit(f"mkqa: {len(refused)} relocation(s) bind this image to its link "
                         f"address ({arch} types {kinds}; first at 0x{refused[0][1]:x}) -- "
                         f"it cannot be moved")
    return sorted(offs)

def imports(elf, base):
    """The IMPORT section: what tools/mkimports.py left for the loader to
    fill, read off the final link's symbols -- `c <off> 8 <name>` a call
    slot to receive the exporter's address, `d <off> <size> <name>` a data
    placeholder to receive a copy of the exporter's object."""
    rows = []
    for name, value, _sz, shndx, _b in elf_symbols(elf):
        if not name.startswith("__qosimp_") or shndx == SHN_UNDEF:
            continue
        kind, _, sym = name[len("__qosimp_"):].partition("_")
        if kind == "c":
            rows.append(f"c {value - base} 8 {sym}")
        elif kind.startswith("d") and kind[1:].isdigit():
            rows.append(f"d {value - base} {int(kind[1:])} {sym}")
        else:
            raise SystemExit(f"mkqa: unknown import marker {name}")
    return sorted(set(rows), key=lambda r: r.split()[3])

def check_moved(image, relocs, other_elf, delta):
    """The same image linked `delta` higher must differ from this one at
    exactly the relocated words, by exactly delta: the list is complete."""
    _b, _e, _x, _r, other, _m = flatten_elf(other_elf)
    if len(other) != len(image):
        raise SystemExit("mkqa: --check-moved: the two links differ in size")
    covered = bytearray(len(image))
    for o in relocs:
        covered[o:o + 8] = b"\x01" * 8
    for o in range(len(image)):
        if image[o] != other[o] and not covered[o]:
            raise SystemExit(f"mkqa: --check-moved: the byte at 0x{o:x} moves with the link "
                             f"address but is not in a relocated word")
    for o in relocs:
        a, = struct.unpack_from("<Q", image, o)
        b, = struct.unpack_from("<Q", other, o)
        if b - a != delta:
            raise SystemExit(f"mkqa: --check-moved: the word at 0x{o:x} moved by {b - a}, not {delta}")

def build(manifest_path, elf_path, out_path, relocatable=False,
          check_moved_elf=None, check_delta=0, with_imports=False, native_abi=None,
          plane_abis=None):
    with open(manifest_path, "rb") as f:
        manifest = f.read()

    if elf_path and elf_path != "-" and os.path.exists(elf_path):
        with open(elf_path, "rb") as f:
            elf = f.read()
        base, entry, execsz, rwoff, image, memsz = flatten_elf(elf)
        if relocatable:
            if base != 0:
                raise SystemExit("mkqa: --relocatable expects an image linked at 0")
            relocs = relocations(elf, base, len(image))
            imps = imports(elf, base) if with_imports else []
            if check_moved_elf:
                with open(check_moved_elf, "rb") as f:
                    check_moved(image, relocs, f.read(), check_delta)
    else:
        base = entry = execsz = rwoff = memsz = 0
        image = b""  # placeholder: name-dispatch era, nothing to load

    load = (f"base {base}\nentry {entry}\nexecsz {execsz}\n"
            f"rwoff {rwoff}\nimagesz {len(image)}\nmemsz {memsz}\n"
            f"sha {hashlib.sha256(image).hexdigest()}\n").encode()

    if native_abi is not None:
        load += f"nativeabi {native_abi}\n".encode()
    if plane_abis is not None:
        # the two plane contracts the image was compiled against (fpr.h
        # FPR_PLANE_ACTORS_ABI / FPR_PLANE_MEMORY_ABI): the loader refuses a
        # mismatch by name before placing the image
        actors_abi, memory_abi = plane_abis
        load += f"planeactors {actors_abi}\nplanememory {memory_abi}\n".encode()

    # RELOC: little-endian u32 offsets of the address words to move by the
    # load address (the image is linked at 0).  IMPORT: one text line per
    # slot or placeholder the loader fills from the running image's export
    # table, by NAME.  Both change what the image does as surely as IMAGE
    # does, so LOAD claims their sha-256 too: `relsha` = sha256(RELOC ||
    # IMPORT), checked beside `sha` (docs/2026-10-03-PREEXISTING-FAILURES.md).
    reloc_b = b"".join(struct.pack("<I", o) for o in relocs) if relocatable else b""
    import_b = "".join(r + "\n" for r in imps).encode() if with_imports else b""
    if relocatable:
        load += f"relsha {hashlib.sha256(reloc_b + import_b).hexdigest()}\n".encode()

    sections = [("MANIFEST", manifest), ("LOAD", load), ("IMAGE", image)]
    if relocatable:
        sections.append(("RELOC", reloc_b))
    if with_imports:
        sections.append(("IMPORT", import_b))
    off = 0
    table_lines = []
    for name, blob in sections:
        table_lines.append(f"{name} {off} {len(blob)}")
        off += len(blob)

    header = b"QAR2\n" + ("\n".join(table_lines)).encode() + b"\n\n"
    with open(out_path, "wb") as f:
        f.write(header)
        for _n, blob in sections:
            f.write(blob)
    extra = f" + {len(relocs)} relocations" if relocatable else ""
    extra += f" + {len(imps)} imports" if with_imports else ""
    print(f"wrote {out_path}: manifest {len(manifest)}B + load {len(load)}B "
          f"+ image {len(image)}B (memsz {memsz}){extra} = {os.path.getsize(out_path)}B total")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("elf", nargs="?", default="-")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--relocatable", action="store_true",
                    help="the ELF is linked at 0 with --emit-relocs: write a RELOC section (native process images)")
    ap.add_argument("--check-moved", metavar="ELF",
                    help="the same image linked --delta higher: verify the RELOC list against it")
    ap.add_argument("--delta", type=lambda x: int(x, 0), default=0)
    ap.add_argument("--imports", action="store_true",
                    help="write an IMPORT section from the image's __qosimp_ markers (Portable plugins)")
    ap.add_argument("--native-abi", type=int, help="shared runtime ABI for a native process image")
    ap.add_argument("--plane-abis", type=int, nargs=2, metavar=("ACTORS", "MEMORY"),
                    help="the plane actors and memory contract versions the process was compiled against")
    a = ap.parse_args()
    if a.native_abi is not None and (not a.relocatable or not 1 <= a.native_abi <= 999999999):
        ap.error("--native-abi needs --relocatable and a positive version of at most nine digits")
    if a.imports and not a.relocatable:
        ap.error("--imports needs --relocatable")
    if a.plane_abis is not None and (a.native_abi is None or not all(1 <= v <= 999999999 for v in a.plane_abis)):
        ap.error("--plane-abis needs --native-abi and two positive versions of at most nine digits")
    build(a.manifest, a.elf, a.out, a.relocatable, a.check_moved, a.delta, a.imports, a.native_abi,
          tuple(a.plane_abis) if a.plane_abis is not None else None)
