#!/usr/bin/env python3
"""Contributor packaging step: stage a native binary desktop SDK (no rebuilding).

The installed builder needs Python >=3.11, Clang and lld on PATH. The release
packager supplies matching prebuilt Main/hosts separately via --profile.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_sdk import API, SESSION, native

ROOT = Path(__file__).resolve().parents[1]


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=True)


def modules(source, destination):
    if source.exists():
        for p in sorted(source.rglob("*")):
            if p.is_file() and (p.suffix in (".fpr", ".txt") or p.name == "versions.db"):
                copy(p, destination / p.relative_to(source))


def revision(tree):
    return subprocess.check_output(["git", "-C", str(tree), "rev-parse", "HEAD"], text=True).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fprisc", type=Path, required=True)
    ap.add_argument("--compiler", type=Path)
    ap.add_argument("--output", type=Path, required=True, help="fresh installation prefix")
    ap.add_argument("--profile", type=Path, help="prebuilt Main profile directory to include")
    args = ap.parse_args()
    prefix = args.output.resolve()
    if prefix.exists():
        ap.error("output already exists; use a fresh prefix")
    fprisc = args.fprisc.resolve()
    compiler = (args.compiler or fprisc / "fpr").resolve()
    if not compiler.is_file():
        ap.error("build the compiler before staging")
    arch = native()[0]
    sdk = prefix / "libexec/qos-portable"
    sdk.mkdir(parents=True)
    copy(compiler, sdk / "compiler/fpr")
    # Library sources and committed blobs are SDK inputs, not compiler/platform
    # source checkouts. No .git, .hs, makefiles or runtime C build is installed.
    for folder in ("core", "std", ".fpr"):
        modules(fprisc / folder, sdk / "compiler" / folder)
    for folder in ("core", "std", "programs/mods", ".fpr"):
        modules(ROOT / folder, sdk / "modules" / folder)
    modules(ROOT / "sdk", sdk / "modules")
    for name in ("portable_sdk.py", "desktop-adapter.fpr.in", "desktop-counter.fpr", "mkimports.py", "mkqa.py", "mkdisk.py"):
        copy(ROOT / "tools" / name, sdk / "tools" / name)
    copy(ROOT / "qos/appside/link-qosplug.ld", sdk / "support/link-qosplug.ld")
    abi = re.search(r"#define\s+QOS_ABI_VERSION\s+(\d+)", (ROOT / "qos/appside/qos_abi.h").read_text())[1]
    meta = dict(format=1, desktopApi=API, desktopSession=SESSION, architecture=arch,
                os=sys.platform, portableAbi=abi, compilerSha256=hashlib.sha256(compiler.read_bytes()).hexdigest(),
                qosRevision=revision(ROOT), fpriscRevision=revision(fprisc),
                qosDirty=bool(subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True)),
                fpriscDirty=bool(subprocess.check_output(["git", "-C", str(fprisc), "status", "--porcelain"], text=True)),
                dependencies=["Python >=3.11", "Clang (ELF assembler)", "lld (ELF linker)"])
    if args.profile:
        if not (args.profile / "main.qa").is_file():
            ap.error("profile must contain a prebuilt main.qa")
        for artifact in [*args.profile.glob("*.qa"), args.profile / "Main.disk"]:
            if artifact.is_file():
                copy(artifact, sdk / "profile" / artifact.name)
        for host in ("qosp", "qosp-gl"):
            copy(ROOT / "qos" / host, sdk / "runtime" / host)
    # The builder is discovered beside the real installed compiler path.
    (sdk / "sdk.json").write_text(json.dumps(meta, indent=2) + "\n")
    binaries = prefix / "bin"
    binaries.mkdir()
    (binaries / "fpr").symlink_to("../libexec/qos-portable/compiler/fpr")
    launcher = binaries / "qos"
    launcher.write_text('#!/bin/sh\nbindir=${0%/*}\nexec python3 "$bindir/../libexec/qos-portable/tools/portable_sdk.py" "$@"\n')
    launcher.chmod(0o755)
    # A hash inventory helps release packaging verify the exact staged inputs.
    inventory = {str(p.relative_to(sdk)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(sdk.rglob("*")) if p.is_file()}
    (sdk / "files.sha256.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"Staged {prefix}; SDK requires Python >=3.11, Clang and lld on PATH")


if __name__ == "__main__":
    main()
