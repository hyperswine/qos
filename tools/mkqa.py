"""mkqa.py -- assemble a .qa (QOS App Archive, QAR2) from a manifest + ELF.

    tools/mkqa.py <manifest.toml> <app.elf> -o out.qa

QAR2 (docs/QA-FORMAT.md): the ELF is consumed HERE, once, at build
time.  Its PT_LOADs are flattened into one image blob; what ships is

    QAR2\n MANIFEST/LOAD/IMAGE table \n\n  payloads

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

def load_sha_of(qa_path):
    """The LOAD section's image sha of an existing .qa -- the identity
    of the shell a plugin links against (the matched-set stamp)."""
    with open(qa_path, "rb") as f:
        b = f.read()
    if b[:5] != b"QAR2\n":
        raise SystemExit(f"mkqa: --shell-of {qa_path}: not a QAR2 archive")
    head, _, _ = b.partition(b"\n\n")
    off = len(head) + 2
    for line in head.decode().split("\n")[1:]:
        name, o, n = line.split()
        if name == "LOAD":
            load = b[off + int(o) : off + int(o) + int(n)].decode()
            for ln in load.split("\n"):
                if ln.startswith("sha "):
                    return ln.split()[1]
    raise SystemExit(f"mkqa: --shell-of {qa_path}: no LOAD sha found")

def build(manifest_path, elf_path, out_path, shell_of=None):
    with open(manifest_path, "rb") as f:
        manifest = f.read()
    if shell_of:
        # stamp the shell identity the plugin was LINKED against; the
        # host refuses an attach under any other shell image (main.c)
        manifest += ('shell = "%s"\n' % load_sha_of(shell_of)).encode()

    if elf_path and elf_path != "-" and os.path.exists(elf_path):
        with open(elf_path, "rb") as f:
            elf = f.read()
        base, entry, execsz, rwoff, image, memsz = flatten_elf(elf)
    else:
        base = entry = execsz = rwoff = memsz = 0
        image = b""  # placeholder: name-dispatch era, nothing to load

    load = (f"base {base}\nentry {entry}\nexecsz {execsz}\n"
            f"rwoff {rwoff}\nimagesz {len(image)}\nmemsz {memsz}\n"
            f"sha {hashlib.sha256(image).hexdigest()}\n").encode()

    off = 0
    table_lines = []
    for name, blob in (("MANIFEST", manifest), ("LOAD", load), ("IMAGE", image)):
        table_lines.append(f"{name} {off} {len(blob)}")
        off += len(blob)

    header = b"QAR2\n" + ("\n".join(table_lines)).encode() + b"\n\n"
    with open(out_path, "wb") as f:
        f.write(header)
        f.write(manifest)
        f.write(load)
        f.write(image)
    print(f"wrote {out_path}: manifest {len(manifest)}B + load {len(load)}B "
          f"+ image {len(image)}B (memsz {memsz}) = {os.path.getsize(out_path)}B total")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("elf", nargs="?", default="-")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--shell-of", help="stamp the manifest with this app .qa's image sha (plugin matched-set gate)")
    a = ap.parse_args()
    build(a.manifest, a.elf, a.out, a.shell_of)
