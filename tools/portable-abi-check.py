#!/usr/bin/env python3
"""Qualify ABI refusal and pin admission against two complete installed SDKs.

Uses temporary disks only. Pass a disk created by the prior SDK; neither the
original disk nor either installed SDK is modified. This checks refusal, not
automatic migration of native images between incompatible ABIs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--prior-sdk", type=Path, required=True)
    parser.add_argument("--prior-disk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deny-source", type=Path, action="append", default=[])
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sdk = args.sdk.resolve() / "libexec/qos-portable"
    prior = args.prior_sdk.resolve() / "libexec/qos-portable"
    meta = json.loads((sdk / "sdk.json").read_text())
    old = json.loads((prior / "sdk.json").read_text())
    assert meta["abi"] != old["abi"], "this check requires an ABI change"
    version = meta["release"]
    assert old["release"].split(".")[:2] != version.split(".")[:2], "ABI change needs a new compatibility series"
    original = args.prior_disk.read_bytes()
    disk = out / "prior.disk"
    disk.write_bytes(original)
    (out / "home").mkdir()
    policy = out / "source-free.sb"
    policy.write_text('(version 1)\n(allow default)\n' + ''.join(
        f'(deny file-read* file-write* (subpath {json.dumps(str(p.resolve()))}))\n'
        for p in [ROOT.parent, Path.home() / ".ghcup", Path.home() / ".cabal", *args.deny_source]))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FPR", "QOS", "GHC"))}
    env.update(HOME=str(out / "home"), XDG_CACHE_HOME=str(out / "cache"),
               PATH="/usr/bin:/bin", FPR_DISK=str(disk), FPR_HARTS="1")
    steps = []

    def run(name, command, cwd=out, refused=None):
        result = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(policy), *map(str, command)],
                                cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
        text = result.stdout + result.stderr
        (out / (name + ".log")).write_text(text)
        assert (result.returncode != 0 if refused else result.returncode == 0), (name, text)
        if refused:
            assert refused.lower() in text.lower(), (name, text)
        steps.append({"name": name, "exit": result.returncode})

    qos = args.sdk.resolve() / "bin/qos"
    run("old-profile-refused", [qos, "run", disk], refused="disk/profile compatibility mismatch")
    run("old-image-refused", [sdk / "runtime/qosp", "--yes", prior / "profile/main.qa"], refused="abi")
    assert disk.read_bytes() == original, "refusal changed the old disk"
    fresh = out / "fresh.disk"
    run("fresh-disk", [qos, "disk", "create", fresh])
    before = fresh.read_bytes()
    run("old-plugin-refused", [qos, "install", prior / "profile/clock.qa", fresh], refused="incompatible ABI")
    assert fresh.read_bytes() == before, "refused install changed the new disk"
    run("new-project", [qos, "new", out / "project"])
    project = out / "project"
    manifest = project / "qos.toml"
    original_manifest = "manifest = 2\n\n" + manifest.read_text()
    for label, pin, accepted in [
        ("compatible", version, True), ("exact", "=" + version, True),
        ("prerelease-minimum", version + "-rc.1", True),
        ("old-series", old["release"], False), ("old-exact", "=" + old["release"], False),
        ("exact-prerelease", "=" + version + "-rc.1", False),
        ("noncanonical", "0" + version, False),
    ]:
        manifest.write_text(original_manifest + "\n[sdk]\nversion = " + json.dumps(pin) + "\n")
        # Admission runs before tool discovery: --version is not a policy check.
        # Accepted builds need Clang; restrict PATH to an explicit symlink.
        if accepted:
            toolpath = out / "path"
            toolpath.mkdir(exist_ok=True)
            clang = toolpath / "clang"
            if not clang.exists():
                clang.symlink_to(shutil.which("clang"))
            env["PATH"] = str(toolpath)
        run("pin-" + label, [qos, "build"], cwd=project, refused=None if accepted else "pin")
    assert args.prior_disk.read_bytes() == original, "original disk changed"
    evidence = dict(status="passed", fromRelease=old["release"], toRelease=version,
                    fromAbi=old["abi"], toAbi=meta["abi"], steps=steps,
                    oldDiskUnchanged=True, rejectedInstallLeftDiskUnchanged=True,
                    oldDiskSha256=hashlib.sha256(original).hexdigest(), sourceAccess="denied",
                    automaticMigration=False)
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print("ABI refusal, disk preservation and seven installed SDK pin cases passed")


if __name__ == "__main__":
    main()
