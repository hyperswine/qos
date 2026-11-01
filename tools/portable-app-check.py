#!/usr/bin/env python3
"""macOS acceptance for kind = "app" projects (docs/2026-11-01-SDK-PROCESS-APPS.md).

Under sandbox-exec, with the folder holding the checkouts, GHC and Cabal
denied and the staged SDK read-only:

1. each --project (a git checkout) is copied out by its tracked files, must
   have no support/ folder, builds with `qos build`, and its own
   `sol tests/check.sol` game check passes (it launches the game through
   `qos run`);
2. the archive records loadMode = "process" and this SDK's platform hash;
3. a copy of the SDK with one platform byte changed is refused by name
   (run last);
4. on the first project, stray platform copies change nothing; a
   [platform.override] of appside/hal.c and an added c-source are built,
   printed, recorded in the archive and run by the game check; an override
   of qos_abi.h is refused;
5. with --baseline (for example the installed 0.2.0), every desktop build
   input except the builder equals the baseline's, and a fresh v1 desktop
   project builds byte-identically with the baseline's builder and this one.

Stages no software itself.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def tree_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def sections(path):
    header, payload = path.read_bytes().split(b"\n\n", 1)
    assert header.startswith(b"QAR2\n")
    return {name.decode(): payload[int(off):int(off) + int(size)]
            for name, off, size in (line.split() for line in header.splitlines()[1:])}


def read_only(prefix):
    for p in sorted(prefix.rglob("*"), reverse=True):
        if not p.is_symlink():
            p.chmod(p.stat().st_mode & ~0o222)
    prefix.chmod(prefix.stat().st_mode & ~0o222)


def writable(prefix):
    prefix.chmod(prefix.stat().st_mode | 0o200)
    for p in prefix.rglob("*"):
        if not p.is_symlink():
            p.chmod(p.stat().st_mode | 0o200)


# What a v1 desktop build reads, apart from the builder (tools/portable_sdk.py).
DESKTOP_INPUTS = ("compiler/", "modules/", "support/", "tools/desktop-adapter.fpr.in",
                  "tools/desktop-counter.fpr", "tools/mkimports.py", "tools/mkqa.py", "tools/qos_archive.py")


def v1_identity(baseline, prefix, out, run, evidence):
    """A v1 desktop project builds byte-identically with the baseline builder and this one.

    The compiler's unit order depends on where the SDK is installed, so two
    SDKs at different paths can emit different bytes from identical inputs
    (0.2.0 does this too). The check therefore requires every other input
    to equal the baseline's, and runs both builders from one SDK location.
    """
    base = baseline / "libexec/qos-portable"
    staged = prefix / "libexec/qos-portable"
    pick = lambda tree: {k: v for k, v in tree_hashes(tree).items() if k.startswith(DESKTOP_INPUTS)}
    assert pick(base) == pick(staged), "staged desktop inputs differ from the baseline SDK's"
    for key in ("abi", "portableAbi", "compilerSha256", "desktopApi", "desktopSession"):
        assert json.loads((base / "sdk.json").read_text())[key] == json.loads((staged / "sdk.json").read_text())[key], key
    sdk = out / "v1-sdk"
    shutil.copytree(prefix, sdk, symlinks=True)
    run([sdk / "bin/qos", "new", "identity"], "v1-scaffold.log")
    run([sdk / "bin/qos", "build"], "v1-staged.log", cwd=out / "identity")
    new = (out / "identity/build/identity.qa").read_bytes()
    shutil.copy2(base / "tools/portable_sdk.py", sdk / "libexec/qos-portable/tools/portable_sdk.py")
    run([sdk / "bin/qos", "build"], "v1-baseline.log", cwd=out / "identity")
    old = (out / "identity/build/identity.qa").read_bytes()
    assert old == new, "v1 desktop build differs from the baseline builder's"
    evidence["v1ByteIdentical"] = dict(archiveSha256=hashlib.sha256(new).hexdigest(), baseline=str(base),
                                       inputsCompared=len(pick(base)))


def overrides(project, sdk, prefix, run, evidence):
    """[platform] overrides: stray copies change nothing; listed ones are built,
    printed, recorded and run; ABI headers are refused."""
    app = tomllib.loads((project / "qos.toml").read_text())["app"]
    archive = project / "build" / f'{app["id"]}.qa'
    original_manifest = (project / "qos.toml").read_text()
    plain = archive.read_bytes()
    # A file that merely sits in the project never shadows the SDK's.
    strays = [project / "platform/appside/hal.c", project / "platform/hal.c", project / "appside/hal.c",
              project / "hal/net_actor_bridge.c", project / "qos_abi.h"]
    for stray in strays:
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text("#error a stray copy must never be compiled\n")
    run([prefix / "bin/qos", "build"], "stray-build.log", cwd=project)
    assert archive.read_bytes() == plain, "a stray platform copy changed the build"
    for stray in strays:
        stray.unlink()
    native = project / "native"
    native.mkdir()
    (native / "hal.c").write_bytes((sdk / "platform/appside/hal.c").read_bytes()
                                   + b'\n__attribute__((used)) const char qos_override_marker[] = "acceptance hal override";\n')
    (native / "sensor.c").write_text('#include "fpr.h"\n'
                                     '__attribute__((used)) const char qos_added_marker[] = "acceptance added source";\n')
    (project / "qos.toml").write_text(original_manifest + '\n[platform]\nc-sources = ["native/sensor.c"]\n'
                                      '\n[platform.override]\n"appside/hal.c" = "native/hal.c"\n')
    printed = run([prefix / "bin/qos", "build"], "override-build.log", cwd=project)
    assert "platform override: appside/hal.c replaced by native/hal.c" in printed, printed
    assert "platform source added: native/sensor.c" in printed, printed
    sec = sections(archive)
    rows = tomllib.loads(sec["MANIFEST"].decode())["platformOverrides"]
    assert [(r["kind"], r.get("file"), r["source"], r["sha256"]) for r in rows] == [
        ("override", "appside/hal.c", "native/hal.c", hashlib.sha256((native / "hal.c").read_bytes()).hexdigest()),
        ("added", None, "native/sensor.c", hashlib.sha256((native / "sensor.c").read_bytes()).hexdigest())], rows
    assert b"acceptance hal override" in sec["IMAGE"] and b"acceptance added source" in sec["IMAGE"]
    run(["sol", "tests/check.sol"], "override-check.log", cwd=project)
    log = (project / "evidence/game.log").read_text()
    assert "replaces the SDK's appside/hal.c with native/hal.c" in log, "qos run did not show the override"
    assert json.loads((project / "evidence/results.json").read_text()).get("passed") is True
    (project / "qos.toml").write_text(original_manifest + '\n[platform.override]\n"appside/qos_abi.h" = "native/hal.c"\n')
    refused = run([prefix / "bin/qos", "build"], "abi-override-refused.log", cwd=project, expect=1)
    assert "part of the SDK's ABI" in refused, refused
    (project / "qos.toml").write_text(original_manifest)
    evidence["overrides"] = dict(project=project.name, strayCopiesIgnored=len(strays), recorded=rows,
                                 gameCheckPassed=True, abiHeaderRefused=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk", type=Path, required=True, help="staged prefix (contains bin/qos)")
    ap.add_argument("--project", type=Path, action="append", required=True, help="kind = \"app\" git checkout")
    ap.add_argument("--baseline", type=Path, help="older SDK prefix for the v1 byte-identity check")
    ap.add_argument("--fprisc", type=Path, default=ROOT.parent / "fprisc")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if sys.platform != "darwin":
        ap.error("this access-denial acceptance runner requires macOS sandbox-exec")
    out, prefix = args.output.resolve(), args.sdk.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sdk = prefix / "libexec/qos-portable"
    meta = json.loads((sdk / "sdk.json").read_text())
    restricted = out / "path"
    restricted.mkdir()
    # sol runs the projects' own checks; fpr and cc build dungeon's host rule suite; the harness sends keys with cat.
    for name in ("python3", "clang", "ld.lld", "sol", "fpr", "cc", "cat"):
        found = shutil.which(name)
        assert found, name
        (restricted / name).symlink_to(Path(found).resolve())
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("FPR", "QOS", "PYTHON", "GHC")) and k not in ("HOME", "PATH", "XDG_CACHE_HOME")}
    env.update(PATH=f"{prefix / 'bin'}:{restricted}", HOME=str(out / "home"),
               XDG_CACHE_HOME=str(out / "cache"), PYTHONDONTWRITEBYTECODE="1")
    (out / "home").mkdir()
    blocked = [ROOT, args.fprisc.resolve(), ROOT.parent, Path.home() / ".ghcup", Path.home() / ".cabal"]
    blocked += [p.resolve() for p in args.project]
    policy = out / "source-free.sb"
    policy.write_text('(version 1)\n(allow default)\n' + ''.join(
        f'(deny file-read* file-write* (subpath {json.dumps(str(path))}))\n' for path in blocked))
    guard = ["/usr/bin/sandbox-exec", "-f", str(policy)]
    evidence = dict(sdk=str(prefix), platformSha256=meta["platformSha256"], compilerSha256=meta["compilerSha256"],
                    denied=list(map(str, blocked)), projects={})

    def run(command, log, cwd=out, expect=0, timeout=900):
        result = subprocess.run(guard + list(map(str, command)), cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=timeout)
        (out / log).write_text(result.stdout + result.stderr)
        assert result.returncode == expect, f"{log}: exit {result.returncode}\n{result.stdout[-3000:]}{result.stderr[-3000:]}"
        return result.stdout + result.stderr

    probe = ('import pathlib, shutil; '
             'assert shutil.which("ghc") is None and shutil.which("cabal") is None; '
             f'paths={list(map(str, [ROOT / "README.md", args.fprisc.resolve() / "core/prelude.fpr", *(p.resolve() / "qos.toml" for p in args.project)]))!r}; '
             '\nfor p in paths:\n try: pathlib.Path(p).read_bytes()\n except PermissionError: pass\n else: raise AssertionError(p)\n'
             'print("checkout access denied; GHC/Cabal absent from PATH")')
    run([restricted / "python3", "-c", probe], "access-probe.log")

    copies = []
    for checkout in args.project:
        checkout = checkout.resolve()
        files = subprocess.check_output(["git", "-C", checkout, "ls-files", "-z"], text=True).split("\0")
        copy = out / checkout.name
        for name in filter(None, files):
            (copy / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(checkout / name, copy / name)
        assert not (copy / "support").exists(), f"{checkout.name} still vendors support/"
        copies.append(copy)

    before = tree_hashes(prefix)
    read_only(prefix)
    try:
        for copy in copies:
            app = tomllib.loads((copy / "qos.toml").read_text())["app"]
            run([prefix / "bin/qos", "build"], f"{copy.name}-build.log", cwd=copy)
            sec = sections(copy / "build" / f'{app["id"]}.qa')
            manifest = tomllib.loads(sec["MANIFEST"].decode())
            assert (manifest["id"], manifest["loadMode"], manifest["abi"], manifest["sdkPlatformSha256"]) == (
                app["id"], "process", meta["abi"], meta["platformSha256"]), manifest
            assert sec["RELOC"] and b"sha " + hashlib.sha256(sec["IMAGE"]).hexdigest().encode() in sec["LOAD"]
            run(["sol", "tests/check.sol"], f"{copy.name}-check.log", cwd=copy)
            result = json.loads((copy / "evidence/results.json").read_text())
            assert result.get("passed") is True, result
            evidence["projects"][copy.name] = dict(archiveSha256=hashlib.sha256((copy / "build" / f'{app["id"]}.qa').read_bytes()).hexdigest(),
                                                   manifest=manifest, checks=result.get("checks"))
            for png in (copy / "evidence").glob("*.png"):
                shutil.copy2(png, out / f"{copy.name}-{png.name}")
        overrides(copies[0], sdk, prefix, run, evidence)
        assert tree_hashes(prefix) == before, "the SDK changed during the acceptance"
    finally:
        writable(prefix)

    if args.baseline:
        v1_identity(args.baseline.resolve(), prefix, out, run, evidence)

    # One changed platform byte is refused by name; nothing is linked from it.
    tampered = out / "tampered"
    shutil.copytree(prefix, tampered, symlinks=True)
    hal = tampered / "libexec/qos-portable/platform/appside/hal.c"
    hal.write_bytes(hal.read_bytes() + b"\n")
    refused = run([tampered / "bin/qos", "build"], "tampered-build.log", cwd=copies[0], expect=1)
    assert "platform file appside/hal.c changed" in refused, refused
    evidence["tamperedPlatformRefused"] = True
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"kind = \"app\" acceptance passed; evidence in {out / 'evidence.json'}")


if __name__ == "__main__":
    main()
