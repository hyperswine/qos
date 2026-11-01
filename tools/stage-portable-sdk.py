#!/usr/bin/env python3
"""Contributor packaging step: stage a native binary desktop SDK (no rebuilding).

The installed `qos` command is FP-RISC (tools/qos/), compiled here by the
SDK's own compiler; the SDK ships no Python. It needs Clang on PATH, and lld
unless --lld gives the static ld.lld the SDK ships (tools/build-sdk-lld.sh).
The release packager supplies matching prebuilt Main/hosts via --profile.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_sdk import API, SESSION, native, platform_digest
import qos_archive

ROOT = Path(__file__).resolve().parents[1]


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=True)


def modules(source, destination):
    if source.exists():
        for p in sorted(source.rglob("*")):
            if p.is_file() and (p.suffix in (".fpr", ".txt") or p.name == "versions.db"):
                copy(p, destination / p.relative_to(source))


# kind = "app" build inputs (docs/2026-11-01-SDK-PROCESS-APPS.md): private,
# hashed, and never a public interface. Installed path -> source path. The
# runtime C and context switch come from the same FP-RISC tree as the
# compiler, so an image never mixes two releases.
def platform_sources(fprisc):
    files = {f"appside/{name}": ROOT / "qos/appside" / name
             for name in ("entry.c", "hal.c", "support.c", "qos_abi.h", "link-qosapp-a64.ld")}
    files.update({"store_abi.h": ROOT / "qos/store_abi.h",  # entry.c: "../store_abi.h"
                  "portable/sha256.c": ROOT / "qos/portable/sha256.c",
                  "loader/qaimg.c": ROOT / "loader/qaimg.c",
                  "hal/net_actor_bridge.c": ROOT / "hal/net_actor_bridge.c",
                  "machine/unix/ctx_a64.S": fprisc / "machine/unix/ctx_a64.S"})
    for name in ("runtime.c", "i32.c", "actors.c", "bits.c", "vec.c", "sstr.c", "mod.c", "buddy.c",
                 "fpr.h", "i32.h", "vec_layout.h"):
        files[f"runtime/{name}"] = fprisc / "runtime" / name
    return files


def build_command(compiler, fprisc, destination):
    """tools/qos/qos.fpr + host.c -> the SDK's `qos` binary."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("FPR_") and k not in ("FPRISC_ROOT", "GHCRTS")}
    env["FPR_HOME"] = str(fprisc)
    env["FPR_NO_RUN_CACHE"] = "1"
    subprocess.run([str(compiler), "build", str(ROOT / "tools/qos/qos.fpr"), "--with", str(ROOT / "tools/qos/host.c"),
                    "-o", str(destination)], env=env, check=True, cwd=ROOT / "tools/qos")


def revision(tree):
    return subprocess.check_output(["git", "-C", str(tree), "rev-parse", "HEAD"], text=True).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fprisc", type=Path, required=True)
    ap.add_argument("--compiler", type=Path)
    ap.add_argument("--output", type=Path, required=True, help="fresh installation prefix")
    ap.add_argument("--profile", type=Path, help="prebuilt Main profile directory to include")
    ap.add_argument("--lld", type=Path, help="a static ld.lld to ship as toolchain/ld.lld (tools/build-sdk-lld.sh)")
    args = ap.parse_args()
    prefix = args.output.resolve()
    if prefix.exists():
        ap.error("output already exists; use a fresh prefix")
    fprisc = args.fprisc.resolve()
    compiler = (args.compiler or fprisc / "fpr").resolve()
    if not compiler.is_file():
        ap.error("build the compiler before staging")
    arch = native()[0]
    if args.profile and not (args.profile / "main.qa").is_file():
        ap.error("profile must contain a prebuilt main.qa")
    sdk = prefix / "libexec/qos-portable"
    sdk.mkdir(parents=True)
    copy(compiler, sdk / "compiler/fpr")
    copy(fprisc / "LICENSE", sdk / "compiler/LICENSE")
    # Library sources and committed blobs are SDK inputs, not compiler/platform
    # source checkouts. No .git, .hs, makefiles or runtime C build is installed.
    for folder in ("core", "std", ".fpr"):
        modules(fprisc / folder, sdk / "compiler" / folder)
    for folder in ("core", "std", "programs/mods", ".fpr"):
        modules(ROOT / folder, sdk / "modules" / folder)
    modules(ROOT / "sdk", sdk / "modules")
    for name in ("desktop-adapter.fpr.in", "desktop-counter.fpr"):
        copy(ROOT / "tools" / name, sdk / "tools" / name)
    # The command itself: FP-RISC with a small C host file, built by the SDK's
    # own compiler and runtime, so the SDK needs no Python.
    build_command(compiler, fprisc, sdk / "tools/qos")
    toolchain = {}
    if args.lld:
        lld = args.lld.resolve()
        linkage = subprocess.check_output(["otool", "-L", str(lld)], text=True).splitlines()[1:]
        if any("/opt/homebrew" in line or "/usr/local" in line or "@rpath" in line for line in linkage):
            ap.error(f"{lld} links libraries outside the system; build it with tools/build-sdk-lld.sh")
        copy(lld, sdk / "toolchain/ld.lld")
        copy(ROOT / "packaging/llvm/LICENSE.TXT", sdk / "toolchain/LICENSE-LLVM.txt")
        toolchain["ld.lld"] = hashlib.sha256((sdk / "toolchain/ld.lld").read_bytes()).hexdigest()
    copy(ROOT / "qos/appside/link-qosplug.ld", sdk / "support/link-qosplug.ld")
    platform_files = {}
    for name, source in sorted(platform_sources(fprisc).items()):
        if not source.is_file():
            ap.error(f"platform input missing: {source}")
        copy(source, sdk / "platform" / name)
        platform_files[name] = hashlib.sha256((sdk / "platform" / name).read_bytes()).hexdigest()
    abi = re.search(r"#define\s+QOS_ABI_VERSION\s+(\d+)", (ROOT / "qos/appside/qos_abi.h").read_text())[1]
    codegen = re.search(r"^codegenRev = (\d+)", (fprisc / "compiler/Codegen.hs").read_text(), re.M)[1]
    meta = dict(format=1, abi=f"{abi}.{codegen}", desktopApi=API, desktopSession=SESSION, architecture=arch,
                os=sys.platform, portableAbi=abi, compilerSha256=hashlib.sha256(compiler.read_bytes()).hexdigest(),
                qosRevision=revision(ROOT), fpriscRevision=revision(fprisc),
                qosDirty=bool(subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True)),
                fpriscDirty=bool(subprocess.check_output(["git", "-C", str(fprisc), "status", "--porcelain"], text=True)),
                dependencies=["Clang (ELF assembler)"] + ([] if toolchain else ["lld (ELF linker)"]),
                platformFiles=platform_files, platformSha256=platform_digest(platform_files))
    if toolchain:
        meta["toolchainFiles"] = toolchain
        meta["toolchainLld"] = subprocess.check_output([str(sdk / "toolchain/ld.lld"), "--version"], text=True).strip()
    if args.profile:
        for artifact in args.profile.glob("*.qa"):
            if artifact.is_file():
                copy(artifact, sdk / "profile" / artifact.name)
        meta['profileFiles'] = {}
        meta['profileApps'] = []
        for artifact in sorted((sdk / 'profile').glob('*.qa')):
            app = qos_archive.read(artifact.read_bytes(), meta['abi'], arch, SESSION, API,
                                   desktop=artifact.name != 'main.qa', bundled=True)
            if artifact.name != 'main.qa':
                meta['profileApps'].append(artifact.name)
            meta['profileFiles'][artifact.name] = app.sha256
        meta['runtimeFiles'] = {}
        for host in ("qosp", "qosp-gl"):
            info = json.loads(subprocess.check_output([str(ROOT / 'qos' / host), '--sdk-info'], text=True))
            if info != {'diskLockContract': 1, 'abi': meta['abi']}:
                ap.error(f'{host} lacks matching ABI/disk lock contract; rebuild the host')
            copy(ROOT / "qos" / host, sdk / "runtime" / host)
            meta['diskLockContract'] = 1
            meta['runtimeFiles'][host] = hashlib.sha256((sdk / 'runtime' / host).read_bytes()).hexdigest()
    # The builder is discovered beside the real installed compiler path.
    (sdk / "sdk.json").write_text(json.dumps(meta, indent=2) + "\n")
    binaries = prefix / "bin"
    binaries.mkdir()
    # Since 0.2.0 the package exports only `qos`: `qos build` selects the private,
    # hash-matched compiler, and global `fpr` belongs to the FP-RISC toolchain.
    (binaries / "qos").symlink_to("../libexec/qos-portable/tools/qos")
    # A hash inventory helps release packaging verify the exact staged inputs.
    inventory = {str(p.relative_to(sdk)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(sdk.rglob("*")) if p.is_file()}
    (sdk / "files.sha256.json").write_text(json.dumps(inventory, indent=2) + "\n")
    needs = "Clang on PATH" if toolchain else "Clang and lld on PATH"
    print(f"Staged {prefix}; SDK requires {needs}")


if __name__ == "__main__":
    main()
