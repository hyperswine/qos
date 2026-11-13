#!/usr/bin/env python3
"""The native `qos` (tools/qos/) against the Python builder it replaces.

    tools/qos-parity-check.py --sdk STAGE --project ../dungeon --project ../terra-ii --output OUT

For one copy of the staged SDK, with the Python builder (tools/portable_sdk.py
and its helpers, from this tree) copied beside the native tools/qos, so both
run from the same SDK location (the compiler's unit order depends on it):

1. a v1 desktop project and each kind = "app" project build to byte-identical
   archives with both builders, and print the same lines;
2. `disk create`, `install` and an update `install` write byte-identical disks;
3. a list of broken qos.toml files is refused with the same message by both,
   apart from TOML syntax errors, which each reader words in its own way.

The native builder runs with PATH holding only /usr/bin and /bin, so it uses
the SDK's own toolchain/ld.lld when the SDK ships one; the Python builder uses
ld.lld from PATH. Evidence is written to OUT/evidence.json.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYTHON_BUILDER = ("portable_sdk.py", "mkimports.sol", "mkexports.sol", "elf-symbols.sol", "sdk/sort.sol",
                  "qa-pack.sol", "elf-image.sol", "qa-relocations.sol", "qa-moved.sol", "qa-imports.sol", "qos_archive.py",
                  "qos_disk.py", "desktop_install.py")

APP_HEAD = '''manifest = 2
[app]
id = "demo"
name = "Demo"
version = "1.0.0"
kind = "app"
[build]
entry = "src/main.fpr"
target = "qos-portable"
'''
# (extra qos.toml text, True when both must give the same message)
REFUSALS = [
    ('[run]\ndisplay = "vga"\n', True), ('[run]\ndisk-mb = 0\n', True), ('[run]\nport = 70000\n', True),
    ('[run]\nport = true\n', True), ('[run]\nbogus = 1\n', True), ('[sdk]\nversion = "1.2"\n', True),
    ('[build2]\nx = 1\n', True), ('[platform]\nc-sources = "x.c"\n', True),
    ('[platform]\nc-sources = ["native/s.c", "native/s.c"]\n', True), ('[platform]\nc-sources = ["/abs.c"]\n', True),
    ('[platform]\nc-sources = ["missing.c"]\n', True), ('[platform]\nc-sources = ["src/main.fpr"]\n', True),
    ('[platform.override]\n"appside/hal.c" = "native/hal.c"\n[platform]\nc-sources = ["native/hal.c"]\n', True),
    ('[platform.override]\n"nope.c" = "native/hal.c"\n', True),
    ('[platform.override]\n"appside/qos_abi.h" = "native/hal.c"\n', True),
    ('[platform.override]\n"appside/link-qosapp-a64.ld" = "native/hal.c"\n', True),
    ('[platform.override]\n"machine/unix/ctx_a64.S" = "native/hal.c"\n', True),
    ('[platform.override]\n"appside/hal.c" = 3\n', True), ('compiler-memory-mb = 0\n', True),
    ('[platform]\nc-sources = ["native/x/s.c"]\n', True),
    # TOML syntax: refused by both, worded by each reader
    ('[build]\noptimize = "fast"\n', False), ('x = 1.5\n', False), ('x = 1\nx = 2\n', False),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk", type=Path, required=True, help="staged prefix (contains bin/qos)")
    ap.add_argument("--project", type=Path, action="append", default=[], help='kind = "app" git checkout')
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    prefix = out / "sdk"
    shutil.copytree(args.sdk.resolve(), prefix, symlinks=True)
    for p in [prefix, *prefix.rglob("*")]:
        if not p.is_symlink():
            p.chmod(p.stat().st_mode | 0o200)
    sdk = prefix / "libexec/qos-portable"
    for name in PYTHON_BUILDER:
        destination = sdk / "tools" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "tools" / name, destination)
    lld = shutil.which("ld.lld")
    base = {k: v for k, v in os.environ.items() if not k.startswith(("FPR", "QOS", "GHCRTS"))}
    native_env = dict(base, PATH="/usr/bin:/bin", HOME=str(out / "home"), XDG_CACHE_HOME=str(out / "cache"))
    python_env = dict(native_env, PATH=f"{Path(lld).parent}:/usr/bin:/bin" if lld else "/usr/bin:/bin")
    (out / "home").mkdir()

    def native(*command, cwd=out):
        return subprocess.run([str(prefix / "bin/qos"), *map(str, command)], cwd=cwd, env=native_env,
                              capture_output=True, text=True, timeout=900)

    def python(*command, cwd=out):
        return subprocess.run(["python3", str(sdk / "tools/portable_sdk.py"), *map(str, command)], cwd=cwd,
                              env=python_env, capture_output=True, text=True, timeout=900)

    evidence = dict(sdk=str(args.sdk.resolve()), nativeLinker=str(sdk / "toolchain/ld.lld") if (sdk / "toolchain/ld.lld").is_file() else "PATH",
                    pythonLinker=lld, builds={}, disks={}, refusals={})

    # 1. archives
    assert native("new", "counter").returncode == 0
    projects = [out / "counter"]
    for checkout in args.project:
        checkout = checkout.resolve()
        copy = out / checkout.name
        files = subprocess.check_output(["git", "-C", checkout, "ls-files", "-z"], text=True).split("\0")
        for name in filter(None, files):
            (copy / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(checkout / name, copy / name)
        projects.append(copy)
    for project in projects:
        app = tomllib.loads((project / "qos.toml").read_text())["app"]
        archive = project / "build" / f'{app["id"]}.qa'
        py = python("build", project)
        assert py.returncode == 0, py.stdout + py.stderr
        old = archive.read_bytes()
        fp = native("build", project)
        assert fp.returncode == 0, fp.stdout + fp.stderr
        new = archive.read_bytes()
        assert old == new, f"{project.name}: the native builder's archive differs"
        # the platform cache key is each builder's own
        strip = lambda text: [l for l in text.splitlines() if not l.startswith("Compiled SDK platform objects")]
        assert strip(py.stdout) == strip(fp.stdout), (py.stdout, fp.stdout)
        evidence["builds"][project.name] = dict(kind=app["kind"], archiveSha256=hashlib.sha256(new).hexdigest(), bytes=len(new))

    # 2. disks
    counter = out / "counter/build/counter.qa"
    for step, command in (("create", ("disk", "create")), ("install", ("install", counter)), ("update", ("install", counter))):
        disks = []
        for run, name in ((python, "python.disk"), (native, "native.disk")):
            argv = [*command, out / name] if step == "create" else [command[0], command[1], out / name]
            r = run(*argv)
            assert r.returncode == 0, r.stdout + r.stderr
            disks.append(out / name)
        assert disks[0].read_bytes() == disks[1].read_bytes(), f"disk {step} differs"
        evidence["disks"][step] = sha(disks[1])

    # 3. refusals
    demo = out / "demo"
    (demo / "src").mkdir(parents=True)
    (demo / "native/x").mkdir(parents=True)
    (demo / "src/main.fpr").write_text("main = print \"demo\".\n")
    (demo / "native/hal.c").write_text("int x;\n")
    (demo / "native/s.c").write_text("int y;\n")
    (demo / "native/x/s.c").write_text("int z;\n")
    (demo / "native/x/qos_abi.h").write_text("/* would shadow */\n")
    for i, (extra, same) in enumerate(REFUSALS):
        (demo / "qos.toml").write_text(APP_HEAD + extra)
        py, fp = python("build", demo), native("build", demo)
        assert py.returncode == 1 and fp.returncode == 1, (extra, py.stderr, fp.stderr)
        last = lambda r: (r.stderr.strip().splitlines() or [""])[-1]
        if same:
            assert last(py) == last(fp), (extra, last(py), last(fp))
        evidence["refusals"][extra.strip()] = dict(python=last(py), native=last(fp), same=last(py) == last(fp))
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"native qos matches the Python builder; evidence in {out / 'evidence.json'}")


if __name__ == "__main__":
    main()
