#!/usr/bin/env python3
"""macOS acceptance for kind = "app" projects (docs/2026-11-01-SDK-PROCESS-APPS.md).

Under sandbox-exec, with the folder holding the checkouts, GHC and Cabal
denied and the staged SDK read-only:

1. each --project (a git checkout) is copied out by its tracked files, must
   have no support/ folder, builds with `qos build`, and its own
   `sol tests/check.sol` game check passes (it launches the game through
   `qos run`);
2. the archive records loadMode = "process" and this SDK's platform hash;
3. a copy of the SDK with one platform byte changed is refused by name;
4. with --baseline, a fresh v1 desktop project builds byte-identically with
   the baseline SDK (for example the installed 0.2.0) and the staged one.

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
        if args.baseline:
            run([args.baseline.resolve() / "bin/qos", "new", "identity"], "v1-scaffold.log")
            run([args.baseline.resolve() / "bin/qos", "build"], "v1-baseline.log", cwd=out / "identity")
            old = (out / "identity/build/identity.qa").read_bytes()
            run([prefix / "bin/qos", "build"], "v1-staged.log", cwd=out / "identity")
            new = (out / "identity/build/identity.qa").read_bytes()
            assert old == new, "v1 desktop build differs from the baseline SDK"
            evidence["v1ByteIdentical"] = hashlib.sha256(new).hexdigest()
        assert tree_hashes(prefix) == before, "the SDK changed during the acceptance"
    finally:
        writable(prefix)

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
