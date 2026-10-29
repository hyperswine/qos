#!/usr/bin/env python3
"""Installed QOS desktop SDK v2: scaffold and native plugin builder.

Python >=3.11, Clang and lld are runtime dependencies. No make, C frontend
runtime build, GHC, Cabal or source checkout is used by this builder.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib

from qos_archive import valid_id

SESSION = "qos.app-session/5"
API = "qos.desktop/2"
ROOT = Path(__file__).resolve().parent.parent


def fail(message):
    raise ValueError(message)


def scaffold(destination):
    destination = Path(destination)
    name = destination.name
    if not valid_id(name):
        fail("app ID: use 1-64 ASCII letters, digits, underscores, dots or hyphens; start with a letter, digit or underscore; no '..'")
    if destination.exists():
        fail(f"{destination} already exists")
    destination.mkdir(parents=True)
    (destination / "assets").mkdir()
    (destination / "assets/.gitkeep").touch()
    (destination / "main.fpr").write_text((ROOT / "tools/desktop-counter.fpr").read_text())
    (destination / ".gitignore").write_text("/build/\n")
    title = name.replace("-", " ").replace("_", " ").title()
    (destination / "qos.toml").write_text(
        f'[app]\nid = {json.dumps(name)}\nname = {json.dumps(title)}\n'
        'version = "0.1.0"\nkind = "desktop"\n\n'
        '[build]\nentry = "main.fpr"\ntarget = "qos-portable"\n')
    print(f"Created {destination}; cd there and run fpr build --target=qos-portable")


def project(path):
    path = Path(path).resolve()
    if path.is_file():
        path = path.parent
    # Project discovery is explicit and bounded to ancestors, like other build tools.
    while not (path / "qos.toml").is_file():
        if path.parent == path:
            fail("no qos.toml in this directory or its parents; use qos new NAME")
        path = path.parent
    data = tomllib.loads((path / "qos.toml").read_text())
    if set(data) != {"app", "build"}:
        fail("qos.toml v1 requires only [app] and [build]")
    app, build = data["app"], data["build"]
    if not isinstance(app, dict) or not isinstance(build, dict):
        fail("[app] and [build] must be TOML tables")
    if set(app) != {"id", "name", "version", "kind"} or set(build) != {"entry", "target"}:
        fail("qos.toml v1 requires app.id/name/version/kind and build.entry/target; unknown keys are refused")
    if not valid_id(app["id"]):
        fail("invalid app.id (archive ID rules; maximum 64 ASCII bytes)")
    for field in ("name", "version"):
        if not isinstance(app[field], str) or not app[field] or any(ord(c) < 32 or c in '"\\' for c in app[field]):
            fail(f"app.{field} must be a nonempty single-line string")
    if app["kind"] != "desktop" or build["target"] != "qos-portable":
        fail("SDK v2 supports kind=desktop and target=qos-portable only")
    if not isinstance(build["entry"], str) or Path(build["entry"]).is_absolute():
        fail("build.entry must be a relative .fpr file inside the project")
    entry = (path / build["entry"]).resolve()
    if not entry.is_relative_to(path) or not entry.is_file() or entry.suffix != ".fpr":
        fail("build.entry must be an existing .fpr file inside the project")
    # Assets have no public runtime lookup contract yet: refuse, never silently omit.
    if (path / "assets").exists() and any(p.is_file() and p.name != ".gitkeep" for p in (path / "assets").rglob("*")):
        fail("asset packaging is not supported by desktop SDK v2")
    return path, app, entry


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native():
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64", "qa64", "a64", "aarch64-none-elf"
    if machine in ("x86_64", "amd64"):
        return "x86_64", "qx64", "x64", "x86_64-none-elf"
    fail(f"desktop SDK v2 does not support {machine}")


def environment(sdk):
    # Do not inherit checkout/module overrides from a contributor's shell.
    env = {k: v for k, v in os.environ.items() if not k.startswith("FPR_") and k != "FPRISC_ROOT"}
    env.update(FPR_HOME=str(sdk / "modules"), FPR_PATH=str(sdk / "compiler"),
               FPR_FOREIGN=str(sdk / "modules/core/foreign.fpr"), LC_ALL="C.UTF-8",
               PYTHONDONTWRITEBYTECODE="1")
    return env


def run(args, env, log, verbose=False):
    command = shlex.join(map(str, args))
    log.write("+ " + command + "\n")
    result = subprocess.run(list(map(str, args)), env=env, capture_output=True, text=True)
    output = result.stdout + result.stderr
    log.write(output)
    log.flush()
    if verbose:
        print("+ " + command)
        print(output, end="")
    if result.returncode:
        if not verbose:
            print("\n".join(output.splitlines()[-60:]), file=sys.stderr)
        fail(f"{Path(args[0]).name} failed; see {log.name}")


def build(where, compiler=None, verbose=False):
    sdk = ROOT
    meta = json.loads((sdk / "sdk.json").read_text())
    arch, target, imports_arch, triple = native()
    if (meta.get("format"), meta.get("desktopApi"), meta.get("desktopSession"), meta.get("os"), meta.get("architecture")) != (
            1, API, SESSION, sys.platform, arch):
        fail("incompatible SDK: install a matching native QOS Portable SDK")
    fpr = (sdk / "compiler/fpr").resolve()
    if compiler and Path(compiler).resolve() != fpr:
        fail("the selected fpr and SDK differ; use this SDK's bin/fpr")
    if digest(fpr) != meta["compilerSha256"]:
        fail("SDK compiler changed; install a matching release set")
    root, app, entry = project(where)
    # Reject quote/control characters rather than interpolate invalid FPR strings.
    if any(c in str(entry) for c in ('"', '\\', '\n', '\r')):
        fail("project path cannot contain quotes, backslashes or newlines")
    out = root / "build"
    if out.is_symlink():
        fail("build/ cannot be a symlink")
    out.mkdir(exist_ok=True)
    env = environment(sdk)
    clang = shutil.which("clang")
    linker = shutil.which("ld.lld")
    if not clang or not linker:
        fail("install Clang and lld and add their bin directories to PATH")
    # Unique intermediate directory; no SDK writes, no stale output publication.
    with tempfile.TemporaryDirectory(prefix=".desktop-", dir=out) as td, (out / "qos-build.log").open("w") as log:
        def command(args):
            run(args, env, log, verbose)

        work = Path(td)
        adapter, asm = work / "entry.fpr", work / "app.s"
        adapter.write_text((sdk / "tools/desktop-adapter.fpr.in").read_text().replace("__ENTRY__", entry.with_suffix("").as_posix()))
        command([fpr, "compile", f"--target={target}", "--plugin", f"--prelude={sdk / 'compiler/core/prelude.fpr'}", adapter, asm])
        units = Path(str(asm) + ".units").read_text().splitlines()
        objects = []
        for i, source in enumerate([str(asm)] + units):
            obj = work / f"unit-{i}.o"
            command([clang, f"--target={triple}", "-c", source, "-o", obj])
            objects.append(obj)
        common = [linker, "-T", sdk / "support/link-qosplug.ld", "--emit-relocs", "--no-relax"]
        first, image, moved = (work / x for x in ("first.elf", "image.elf", "moved.elf"))
        command(common + ["--defsym=PLUG_BASE=0", "--unresolved-symbols=ignore-all", *objects, "-o", first])
        stub = work / "imports.s"
        command([sys.executable, sdk / "tools/mkimports.py", "--arch", imports_arch, first, "-o", stub])
        stub_obj = work / "imports.o"
        command([clang, f"--target={triple}", "-c", stub, "-o", stub_obj])
        for base, dest in (("0", image), ("0x10000000", moved)):
            command(common + [f"--defsym=PLUG_BASE={base}", *objects, stub_obj, "-o", dest])
        revision = Path(str(asm) + ".abirev").read_text().strip()
        if meta.get("abi") != f'{meta["portableAbi"]}.{revision}':
            fail("SDK compiler/profile ABI mismatch; reinstall a matching SDK")
        fields = dict(name=app["name"], id=app["id"], version=app["version"], entry="fpr_modtab", loadMode="plugin",
                      abi=f'{meta["portableAbi"]}.{revision}', architecture=arch, desktopSession=SESSION, desktopApi=API)
        manifest = work / "manifest.toml"
        manifest.write_text("".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in fields.items()))
        archive = work / "app.qa"
        command([sys.executable, sdk / "tools/mkqa.py", manifest, image, "-o", archive,
             "--relocatable", "--imports", "--check-moved", moved, "--delta", "0x10000000"])
        destination = out / f'{app["id"]}.qa'
        archive.replace(destination)
    print(f"Built {destination}")
    return destination


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", action="store_true", help="show installed release and API versions")
    sub = ap.add_subparsers(dest="command")
    p = sub.add_parser("new")
    p.add_argument("destination")
    p = sub.add_parser("build")
    p.add_argument("project", nargs="?", default=".")
    p.add_argument("--compiler")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("disk")
    disks = p.add_subparsers(dest="disk_command", required=True)
    p = disks.add_parser("create")
    p.add_argument("destination")
    p.add_argument("--profile", choices=["main"], default="main")
    p.add_argument("--size", type=int, default=32, help="disk size in MiB")
    p = sub.add_parser("install")
    p.add_argument("archive", nargs="?")
    p.add_argument("destination", nargs="?")
    p.add_argument("--prefix", help=argparse.SUPPRESS)
    p = sub.add_parser("run")
    p.add_argument("disk")
    args = ap.parse_args()
    if args.version:
        meta = json.loads((ROOT / "sdk.json").read_text())
        print(f"QOS Portable {meta.get('release', 'development')} ({API}, {SESSION})")
        return
    if not args.command:
        ap.error("choose a command (see --help)")
    try:
        if args.command == "new":
            scaffold(args.destination)
        elif args.command == "build":
            build(args.project, args.compiler, args.verbose)
        else:
            import desktop_install
            if args.command == "disk":
                desktop_install.create(ROOT, args.destination, args.size)
            elif args.command == "install":
                if args.prefix is not None:
                    fail("toolchain installation moved to qos toolchain install --prefix (contributor CLI)")
                if not args.archive or not args.destination:
                    fail("usage: qos install APP.qa DISK")
                desktop_install.install(ROOT, args.archive, args.destination)
            elif args.command == "run":
                sys.exit(desktop_install.run(ROOT, args.disk))
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"qos: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
