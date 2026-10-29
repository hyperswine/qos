"""Offline QAR2 desktop validation, including the native module entry table.

Native code remains trusted cooperative code. Integrity and structural checks
are compatibility/corruption checks, not a sandbox or a signature verifier.
"""
from dataclasses import dataclass
import hashlib
import re
import struct
import tomllib


def require(ok, why):
    if not ok:
        raise ValueError(why)


def valid_id(value):
    return (isinstance(value, str) and 0 < len(value.encode()) <= 64
            and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", value) is not None
            and ".." not in value)


def sections(raw):
    require(raw.startswith(b"QAR2\n") and b"\n\n" in raw, "not a QAR2 archive")
    table, payload = raw.split(b"\n\n", 1)
    result, cursor = {}, 0
    for row in table.splitlines()[1:]:
        match = re.fullmatch(rb'([A-Z][A-Z0-9_]*) (0|[1-9][0-9]*) (0|[1-9][0-9]*)', row)
        require(match is not None, "invalid QAR2 section table")
        name, offset, size = match.groups()
        name, offset, size = name.decode(), int(offset), int(size)
        require(name not in result and offset == cursor and size <= len(payload) - offset,
                "duplicate, overlapping or out-of-range archive section")
        result[name] = payload[offset:offset + size]
        cursor += size
    require(cursor == len(payload), "archive has unclaimed trailing bytes")
    require({"MANIFEST", "LOAD", "IMAGE", "RELOC"} <= result.keys(), "archive lacks a required image/relocation section")
    return result


@dataclass(frozen=True)
class Archive:
    raw: bytes
    manifest: dict
    parts: dict
    load: dict

    @property
    def id(self):
        return self.manifest["id"]

    @property
    def sha256(self):
        return hashlib.sha256(self.raw).hexdigest()


def read(raw, abi, architecture, session, api, *, desktop=True, bundled=False):
    parts = sections(raw)
    manifest = tomllib.loads(parts["MANIFEST"].decode("utf-8"))
    require(valid_id(manifest.get("id")), "invalid archive manifest ID")
    for field in ("name", "version"):
        value = manifest.get(field)
        require(isinstance(value, str) and value and not any(ord(c) < 32 or c in '"\\' for c in value),
                f"invalid archive {field}")
    require(manifest.get("abi") == abi, f"incompatible ABI; rebuild for {abi}")
    if desktop:
        require(manifest.get("loadMode") == "plugin" and manifest.get("entry") == "fpr_modtab",
                "Main desktop apps must be plugins with entry=fpr_modtab")
        require("IMPORT" in parts, "desktop plugin lacks IMPORT section")
    else:
        require(manifest.get("loadMode") == "process", "Main entry must be a process archive")
    for field, expected in (("architecture", architecture), ("desktopSession", session), ("desktopApi", api)):
        # Legacy onboard plugins come from the pinned profile with verified hashes.
        # External archives must carry the full desktop compatibility contract.
        require((bundled and field != "architecture" and field not in manifest) or manifest.get(field) == expected,
                f"incompatible/missing {field}; rebuild with this installed SDK")
    require(not manifest.get("permissions"), "desktop SDK does not support archive permission declarations")
    fields = {}
    for line in parts["LOAD"].decode("ascii").splitlines():
        words = line.split(" ")
        require(len(words) == 2 and words[0] not in fields, "invalid/duplicate LOAD field")
        key, value = words
        if key in ("sha", "relsha"):
            require(re.fullmatch(r"[0-9a-f]{64}", value), "invalid LOAD hash")
            fields[key] = value
        else:
            require(key in ("base", "entry", "execsz", "rwoff", "imagesz", "memsz", "nativeabi", "planeactors", "planememory")
                    and re.fullmatch(r"0|[1-9][0-9]*", value), "invalid LOAD number")
            fields[key] = int(value)
            require(fields[key] <= (1 << 62) - 1, "LOAD number exceeds the runtime Int range")
    require({"base", "entry", "execsz", "rwoff", "imagesz", "memsz", "sha", "relsha"} <= fields.keys(), "incomplete LOAD section")
    image, rel, imp = parts["IMAGE"], parts["RELOC"], parts.get("IMPORT", b"")
    require(fields["base"] == 0 and 0 <= fields["entry"] < fields["execsz"] <= len(image) == fields["imagesz"] <= fields["memsz"]
            and 0 <= fields["rwoff"] <= fields["memsz"], "inconsistent LOAD image spans")
    require(hashlib.sha256(image).hexdigest() == fields["sha"], "IMAGE sha256 mismatch")
    require(hashlib.sha256(rel + imp).hexdigest() == fields["relsha"], "RELOC/IMPORT sha256 mismatch")
    require(len(rel) % 4 == 0, "invalid RELOC byte length")
    offsets = [row[0] for row in struct.iter_unpack("<I", rel)]
    require(offsets == sorted(set(offsets)), "duplicate/unsorted RELOC offsets")
    for at in offsets:
        require(at % 8 == 0 and at + 8 <= len(image), "out-of-range/unaligned RELOC word")
        pointer, = struct.unpack_from("<Q", image, at)
        require(pointer <= fields["memsz"], "RELOC pointer outside image")
    spans = []
    for row in imp.splitlines():
        match = re.fullmatch(rb'([cd]) (0|[1-9][0-9]*) (0|[1-9][0-9]*) (fpr_[A-Za-z0-9_.$]+)', row)
        require(match is not None, "invalid IMPORT row")
        kind, at, size, name = match.groups()
        at, size = int(at), int(size)
        expected = 8 if name in (b"fpr_true", b"fpr_false", b"fpr_unit", b"fpr_g_tlsoff") else 32 if name.startswith(b"fpr_g_") and not re.search(rb'_call[0-9]+$', name) else None
        require((kind == b'c' and size == 8 and expected is None) or (kind == b'd' and size == expected), "invalid IMPORT object kind/size")
        require(at % 8 == 0 and 0 < size and at + size <= len(image), "out-of-range IMPORT slot")
        spans.append((at, at + size))
    spans.sort()
    require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), "overlapping IMPORT slots")
    require(all(not any(a < offset + 8 and offset < b for a, b in spans) for offset in offsets), "IMPORT overlaps RELOC")
    if desktop:
        check_entry(image, fields["entry"], fields["execsz"], set(offsets))
    return Archive(raw, manifest, parts, fields)


def check_entry(image, entry, executable, relocs):
    def words(at, count):
        require(at % 8 == 0 and 0 <= at <= len(image) - 8 * count, "module table pointer outside IMAGE")
        return struct.unpack_from("<" + "Q" * count, image, at)

    def string(at):
        header, size = words(at, 2)
        require(header == 9000 and size <= len(image) - at - 16, "invalid module string")
        return image[at + 16:at + 16 + size]

    magic, schema, root_at = words(entry, 3)
    require((magic, schema) == (0x4650524D, 1), "unsupported module table schema")
    require(entry + 16 in relocs, "unrelocated module root")
    root = string(root_at)
    require(root != b"", "missing root module identity")
    at, found = entry + 24, 0
    while True:
        first, = words(at, 1)
        if first == 0:
            break
        scope, name, pap, interface = words(at, 4)
        require(all(at + i * 8 in relocs for i in range(4)), "unrelocated module table row")
        row_scope, row_name = string(scope), string(name)
        string(interface)
        header, fn, arity, nargs = words(pap, 4)
        require(header == 9001 and fn < executable and arity > 0 and nargs == 0 and pap + 8 in relocs, "invalid module function closure")
        if row_scope == root and row_name == b"appMain":
            require(arity == 1, "appMain must take one actor argument")
            found += 1
        at += 32
    require(found == 1, "desktop archive needs exactly one root appMain export")
