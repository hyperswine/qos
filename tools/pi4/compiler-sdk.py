#!/usr/bin/env python3
"""Build a relocatable native AArch64 Editor compiler SDK on ARM64 Linux.

The archive contains a prebuilt compiler, Python, make, and the GNU assembly
link pipeline. It does not contain a C compiler frontend, LLVM, a libc, or a
dynamic loader. The target supplies glibc at least as new as the build host.
Run in the same pinned build container used to build the compiler.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import zipfile


SYSTEM_LIBS = re.compile(r"^(?:ld-linux.*|lib(?:c|m|pthread|dl|rt|resolv|util)\.so(?:\..*)?)$")


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def copy(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(src).resolve(), dest)


def sources(src, dest, suffixes):
    for path in sorted(src.rglob("*")):
        if path.is_file() and path.suffix in suffixes:
            copy(path, dest / path.relative_to(src))


def provenance(tree, explicit):
    try:
        revision = subprocess.check_output(["git", "-C", str(tree), "rev-parse", "HEAD"],
                                           text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(run("git", "-C", str(tree), "status", "--porcelain"))
    except subprocess.CalledProcessError:
        if not explicit:
            raise SystemExit(f"source export {tree} needs an explicit revision argument")
        revision, dirty = explicit, None
    if explicit and revision != explicit:
        raise SystemExit(f"source revision mismatch: {revision} != {explicit}")
    return revision, dirty


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--qos", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--fprisc", type=Path, required=True)
    ap.add_argument("--compiler", type=Path, required=True)
    ap.add_argument("--compiler-kind", choices=("full", "editor"), default="full")
    ap.add_argument("--qos-revision", help="required for a source export without .git")
    ap.add_argument("--fprisc-revision", help="required for a source export without .git")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-compressed-mib", type=int, default=40)
    args = ap.parse_args()
    if sys.platform != "linux" or platform.machine() not in ("aarch64", "arm64"):
        ap.error("build with native Python on AArch64 Linux")
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    qos_revision, qos_dirty = provenance(args.qos, args.qos_revision)
    fprisc_revision, fprisc_dirty = provenance(args.fprisc, args.fprisc_revision)
    roots = []
    with tempfile.TemporaryDirectory(prefix="qos-sdk-") as td:
        sdk = Path(td) / "sdk"
        for folder in ("bin", "lib", "qos", "fprisc", "python/lib"):
            (sdk / folder).mkdir(parents=True, exist_ok=True)
        for name in ("make", "gcc", "as", "ld"):
            binary = shutil.which(name)
            if not binary:
                ap.error(f"missing {name}")
            copy(binary, sdk / "bin" / name)
            roots.append(sdk / "bin" / name)
        collect = Path(run("gcc", "-print-prog-name=collect2"))
        if not collect.is_file():
            ap.error("gcc collect2 not found")
        copy(collect, sdk / "bin/collect2")
        roots.append(sdk / "bin/collect2")
        copy(args.compiler, sdk / "fprisc/fpr")
        roots.append(sdk / "fprisc/fpr")
        (sdk / "fprisc/fprc").symlink_to("fpr")
        # Only the portable plugin recipes are invoked. .installed prevents
        # make from attempting to rebuild the Haskell compiler on the Pi.
        for name in ("Makefile", "dependency.mk", "qos-app.mk"):
            copy(args.qos / name, sdk / "qos" / name)
        (sdk / "qos/.installed").touch()
        (sdk / "qos/toolchain").symlink_to("../fprisc")
        for folder in ("core", "std", "programs/mods"):
            sources(args.qos / folder, sdk / "qos" / folder, {".fpr", ".txt"})
        for name in ("qos_abi.h", "link-qosplug.ld"):
            copy(args.qos / "qos/appside" / name, sdk / "qos/qos/appside" / name)
        copy(args.qos / "hal/virt/qos-virt.mk", sdk / "qos/hal/virt/qos-virt.mk")
        for name in ("fprd.py", "mkqa.py", "mkimports.py"):
            copy(args.qos / "tools" / name, sdk / "qos/tools" / name)
        for folder in ("core", "std"):
            sources(args.fprisc / folder, sdk / "fprisc" / folder, {".fpr", ".txt"})
        # A pinned use can resolve an older source blob even when today's
        # working module has changed. Ship sources/metadata, never caches.
        for tree, name in ((args.qos, "qos"), (args.fprisc, "fprisc")):
            store = tree / ".fpr"
            if (store / "versions.db").is_file():
                copy(store / "versions.db", sdk / name / ".fpr/versions.db")
            sources(store / "store", sdk / name / ".fpr/store", {".fpr"})
        for name in ("Main.hs", "Codegen.hs"):
            copy(args.fprisc / "compiler" / name, sdk / "fprisc/compiler" / name)
        copy(args.qos / "tools/pi4/compiler-sdk-run.py", sdk / "run.py")
        if args.compiler_kind == "editor":
            copy(args.qos / "tools/pi4/EditorCompiler.hs", sdk / "qos/tools/pi4/EditorCompiler.hs")
        launcher = sdk / "bin/qos-fprd"
        launcher.write_text('''#!/bin/sh
set -eu
SDK=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONHOME="$SDK/python"
export PYTHONNOUSERSITE=1
export LD_LIBRARY_PATH="$SDK/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$SDK/bin/python3" -S "$SDK/run.py" "$@"
''')
        launcher.chmod(0o755)
        pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
        copy(sys.executable, sdk / "bin/python3")
        roots.append(sdk / "bin/python3")
        stdlib = Path(sysconfig.get_path("stdlib"))
        # A complete pure-Python stdlib keeps the daemon and packaging tools
        # independent of distro/site packages. Tests/GUI/docs are not runtime.
        archive = sdk / "python/lib" / ("python" + pyver.replace(".", "") + ".zip")
        excluded = {"test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "venv", "site-packages", "dist-packages", "__pycache__"}
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for path in sorted(stdlib.rglob("*.py")):
                relative = path.relative_to(stdlib)
                if not any(part in excluded for part in relative.parts):
                    z.write(path, str(relative))
        dyn = sdk / "python/lib" / ("python" + pyver) / "lib-dynload"
        for path in sorted(Path(sysconfig.get_config_var("DESTSHARED")).glob("*.so")):
            # Editor tooling needs no network TLS, GUI, database, C FFI,
            # compression codecs beyond zip's zlib, or asynchronous loop.
            if path.name.split(".")[0] in {"_tkinter", "_ssl", "_hashlib", "_ctypes", "_curses", "_curses_panel", "_sqlite3", "_dbm", "_gdbm", "_bz2", "_lzma", "_decimal", "_asyncio", "readline"}:
                continue
            copy(path, dyn / path.name)
            roots.append(dyn / path.name)
        # Resolve and recursively copy every ELF dependency, excluding the
        # target's matching glibc/loader family. No build-host rpath is needed.
        visited = set()
        while roots:
            binary = roots.pop()
            for line in run("ldd", str(binary)).splitlines():
                match = re.match(r"\s*(\S+) => (/\S+)", line)
                if not match:
                    if "not found" in line:
                        raise RuntimeError(f"unresolved SDK library: {line}")
                    continue
                soname, path = match.groups()
                if soname in visited or SYSTEM_LIBS.fullmatch(soname):
                    continue
                visited.add(soname)
                target = sdk / "lib" / soname
                copy(path, target)
                roots.append(target)
        for path in sorted(sdk.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.read_bytes()[:4] == b"\x7fELF":
                subprocess.run(["strip", "--strip-unneeded", str(path)], check=True)
        source_hash = hashlib.sha256()
        for path in sorted((sdk / "qos").rglob("*")) + sorted((sdk / "fprisc").rglob("*")):
            if path.is_file() and not path.is_symlink() and (path.name == "Makefile" or path.suffix in {".py", ".fpr", ".hs", ".h", ".txt", ".ld", ".mk", ".db"}):
                source_hash.update(str(path.relative_to(sdk)).encode() + b"\0" + path.read_bytes() + b"\0")
        (sdk / "sdk.json").write_text(json.dumps({
            "format": 1, "arch": platform.machine(), "python": pyver,
            "compiler_kind": args.compiler_kind,
            "entrypoint_sha256": (hashlib.sha256((args.qos / "tools/pi4/EditorCompiler.hs").read_bytes()).hexdigest()
                                  if args.compiler_kind == "editor" else None),
            "glibc": run("getconf", "GNU_LIBC_VERSION"),
            "qos_revision": qos_revision, "fprisc_revision": fprisc_revision,
            "qos_dirty": qos_dirty, "fprisc_dirty": fprisc_dirty,
            "bundled_source_sha256": source_hash.hexdigest(),
            "compiler_input_sha256": hashlib.sha256(args.compiler.read_bytes()).hexdigest(),
            "compiler_sha256": hashlib.sha256((sdk / "fprisc/fpr").read_bytes()).hexdigest(),
        }, indent=2) + "\n")
        expanded = sum(p.stat().st_size for p in sdk.rglob("*") if p.is_file() and not p.is_symlink())
        with tarfile.open(args.output, "w:gz", compresslevel=9) as tar:
            tar.add(sdk, arcname=".", recursive=True)
        size = args.output.stat().st_size
        if size > args.max_compressed_mib * 1024 * 1024:
            raise SystemExit(f"SDK exceeds {args.max_compressed_mib} MiB compressed: {size}")
        digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
        args.output.with_suffix(args.output.suffix + ".sha256").write_text(f"{digest}  {args.output.name}\n")
        print(json.dumps({"archive": str(args.output), "compressed_bytes": size,
                          "expanded_bytes": expanded, "sha256": digest}))


if __name__ == "__main__":
    main()
