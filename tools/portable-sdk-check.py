#!/usr/bin/env python3
"""macOS installed-SDK acceptance: deny checkout/GHC/Cabal access, build and run.

Stages no software itself. Pass a fresh staged prefix and a prebuilt
 tests/sdkdesktop.fpr driver. --gui additionally opens prebuilt Main and
captures the external counter before/after a key, then closes cleanly.
Exercises disk create, install/update and run using fresh throwaway disks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import sys
import threading
import time
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk", type=Path, required=True, help="staged prefix (contains bin/)")
    ap.add_argument("--driver", type=Path, required=True)
    ap.add_argument("--fprisc", type=Path, default=ROOT.parent / "fprisc")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--gui", action="store_true")
    args = ap.parse_args()
    if sys.platform != "darwin":
        ap.error("this access-denial acceptance runner currently requires macOS sandbox-exec")
    out, prefix = args.output.resolve(), args.sdk.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sdk = prefix / "libexec/qos-portable"
    shutil.copy2(args.driver, out / "driver.qa")
    restricted = out / "path"
    restricted.mkdir()
    for name in ("python3", "clang", "ld.lld"):
        found = shutil.which(name)
        assert found, name
        (restricted / name).symlink_to(Path(found).resolve())
    # Installed SDK must remain read-only, including bytecode/module caches.
    before = tree_hashes(prefix)
    for p in sorted(prefix.rglob("*"), reverse=True):
        if not p.is_symlink():
            p.chmod(p.stat().st_mode & ~0o222)
    prefix.chmod(prefix.stat().st_mode & ~0o222)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("FPR", "QOS", "PYTHON")) and k not in ("HOME", "PATH", "XDG_CACHE_HOME")}
    env.update(PATH=f"{prefix / 'bin'}:{restricted}", HOME=str(out / "home"),
               XDG_CACHE_HOME=str(out / "cache"), PYTHONDONTWRITEBYTECODE="1")
    (out / "home").mkdir()
    # The folder holding the checkouts also covers sibling worktrees and the main checkouts.
    blocked = [ROOT, args.fprisc.resolve(), ROOT.parent, Path.home() / ".ghcup", Path.home() / ".cabal"]
    policy = out / "source-free.sb"
    policy.write_text('(version 1)\n(allow default)\n' + ''.join(
        f'(deny file-read* file-write* (subpath {json.dumps(str(path))}))\n' for path in blocked))
    guard = ["/usr/bin/sandbox-exec", "-f", str(policy)]

    def run(command, log, cwd=out, extra=None, expect=0):
        result = subprocess.run(guard + list(map(str, command)), cwd=cwd, env=dict(env, **(extra or {})),
                                capture_output=True, text=True, timeout=180)
        (out / log).write_text(result.stdout + result.stderr)
        assert result.returncode == expect, f"{log}: exit {result.returncode}\n{result.stdout[-2000:]}{result.stderr[-2000:]}"
        return result.stdout + result.stderr

    # Prove the guard actually denies both checkouts and both build tools.
    probe = ('import pathlib, shutil; '
             'assert shutil.which("ghc") is None and shutil.which("cabal") is None; '
             'assert shutil.which("make") is None; '
             f'paths={list(map(str, [ROOT / "README.md", args.fprisc.resolve() / "core/prelude.fpr"]))!r}; '
             '\nfor p in paths:\n try: pathlib.Path(p).read_bytes()\n except PermissionError: pass\n else: raise AssertionError(p)\n'
             'print("checkout access denied; GHC/Cabal/make absent from PATH")')
    run([restricted / "python3", "-c", probe], "access-probe.log")
    run([prefix / "bin/qos", "new", "counter-example"], "scaffold.log")
    project = out / "counter-example"
    # Both directory and source filename can change without changing identity.
    project.rename(out / "renamed project")
    project = out / "renamed project"
    (project / "main.fpr").rename(project / "counter.fpr")
    manifest = project / "qos.toml"
    manifest.write_text(manifest.read_text().replace('"main.fpr"', '"counter.fpr"').replace('"Counter Example"', '"External Counter"').replace('"0.1.0"', '"1.2.3"'))
    run([prefix / "bin/qos", "build"], "build.log", cwd=project,
        extra={"FPR_HOME": str(ROOT), "FPR_PATH": str(args.fprisc), "FPR_FOREIGN": str(ROOT / "core/foreign.fpr")})
    archive = project / "build/counter-example.qa"
    sec = sections(archive)
    app = tomllib.loads(sec["MANIFEST"].decode())
    assert (app["id"], app["name"], app["version"], app["loadMode"], app["desktopSession"]) == (
        "counter-example", "External Counter", "1.2.3", "plugin", "qos.app-session/5")
    assert sec["IMPORT"] and sec["RELOC"] and sec["IMAGE"]
    assert b"sha " + hashlib.sha256(sec["IMAGE"]).hexdigest().encode() in sec["LOAD"]
    run([prefix / "bin/qos", "build", "--manifest=cost.toml"],
        "cost-option-refused.log", cwd=project, expect=2)
    # A second app proves initial commands, wire result conversion and cleanup.
    run([prefix / "bin/qos", "new", "clock-example"], "clock-scaffold.log")
    clock = out / "clock-example"
    (clock / "main.fpr").write_text('''unsafe module.
D = use "qos/desktop".
init = (False, [D.Fetch 1 D.Clock]).
update (D.Arrived 1 (Ok (D.Time seconds))) ready = (True, Nil).
update event ready = (ready, Nil).
view viewport ready = (D.text viewport "Clock effect" "" Nil, Nil,
  if ready then "clock ready" else "clock waiting").
''')
    run([prefix / "bin/qos", "build"], "clock-build.log", cwd=clock)
    disk = out / "counter.disk"
    run([prefix / "bin/qos", "disk", "create", disk, "--profile", "main", "--size", "32"], "disk-create.log")
    tools = str(sdk / "tools")
    seed = (f"import sys;sys.path.insert(0,{tools!r});import qos_disk as d;"
            f"\nwith d.locked({str(disk)!r}) as fd: d.append(fd,d.metadata(fd),[(b'user/note',b'keep this'),(b'user/history',b'unchanged')])")
    run([restricted / "python3", "-c", seed], "user-record-seed.log")

    def values(log):
        probe = (f"import sys,json,hashlib;sys.path.insert(0,{tools!r});import qos_disk as d;"
                 f"\nwith d.locked({str(disk)!r}) as fd: print(json.dumps({{k.decode():hashlib.sha256(v.read(fd)).hexdigest() for k,v in d.scan(fd,d.metadata(fd)).items()}},sort_keys=True))")
        return json.loads(run([restricted / "python3", "-c", probe], log))

    original_records = values("before-install-values.json")
    run([prefix / "bin/qos", "install", archive, disk], "counter-install.log")
    run([prefix / "bin/qos", "install", clock / "build/clock-example.qa", disk], "clock-install.log")
    run([prefix / "bin/qos", "install", "--prefix", out / "unused"], "old-toolchain-option-refused.log", expect=1)
    # First process saves real app state before the archive is replaced.
    first = run([sdk / "runtime/qosp", "--yes", out / "driver.qa"], "session-1.log",
                extra={"FPR_DISK": str(disk), "FPR_HARTS": "1"})
    assert "sdkdesktop: HOLDS persisted=1 loaded=0" in first, first
    before_update = values("before-update-values.json")
    original_archive = archive.read_bytes()
    manifest.write_text(manifest.read_text().replace('"1.2.3"', '"1.2.4"'))
    source = project / "counter.fpr"
    source.write_text(source.read_text().replace('viewport "Counter"', 'viewport "Counter Updated"'))
    run([prefix / "bin/qos", "build"], "update-build.log", cwd=project)
    assert archive.read_bytes() != original_archive
    run([prefix / "bin/qos", "install", archive, disk], "counter-update.log")
    app = tomllib.loads(sections(archive)["MANIFEST"].decode())
    assert app["version"] == "1.2.4"
    updated_records = values("after-update-values.json")
    assert all(updated_records[k] == v for k, v in original_records.items() if k != "apps/index"), "installer changed unrelated app/user records"
    assert updated_records["apps/counter-example.qa"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert all(updated_records[k] == v for k, v in before_update.items() if k not in ("apps/index", "apps/counter-example.qa")), "app update changed saved state"
    # The real QLOG reader below will prove that Python's bulk framing and
    # durable metadata interoperate with the production FP-RISC implementation.
    second = run([sdk / "runtime/qosp", "--yes", out / "driver.qa"], "session-4.log",
                 extra={"FPR_DISK": str(disk), "FPR_HARTS": "4"})
    assert "sdkdesktop: HOLDS persisted=1 loaded=1" in second, second
    if args.gui:
        gui(out, sdk, guard, env, disk)
        after_launch = values("after-main-values.json")
        assert all(after_launch[k] == v for k, v in updated_records.items() if not k.startswith("app-data/counter-example/")), "Main launch changed unrelated app/user records"
        assert after_launch["app-data/counter-example/636f756e74"] == hashlib.sha256(b"2").hexdigest(), "graphical counter did not save the increment"
    assert tree_hashes(prefix) == before, "SDK modified during build or runtime"
    evidence = dict(result="passed", os=sys.platform, architecture=app["architecture"],
                    sourceAccess="denied by sandbox-exec", absentTools=["ghc", "cabal", "make"],
                    readOnlySdkUnchanged=True, app=app, archiveSha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    sessionHarts=[1, 4], clockEffect=True, graphicalMain=args.gui,
                    offlineInstallUpdate=True, persistentAppStore=True, storeSurvivesAppReplacement=True, storeSurvivesHostRestart=True,
                    isolatedAppIdentities=True, closeDrainsPendingSave=True, unrelatedRecordsPreserved=True, hostInstallerExclusion=args.gui,
                    sdk=json.loads((sdk / "sdk.json").read_text()))
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"installed SDK: HOLDS ({out / 'evidence.json'})")


def gui(out, sdk, guard, env, disk):
    fifo = out / "keys.evd"
    os.mkfifo(fifo)
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    prefix = sdk.parents[1]
    proc = subprocess.Popen(guard + [str(prefix / "bin/qos"), "run", str(disk)],
        cwd=out, env=dict(env, FPR_DISK=str(disk), FPR_EVDEV=str(fifo)),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    messages, lines = queue.Queue(), []

    def reader():
        for line in proc.stdout:
            lines.append(line)
            messages.put(line)
        messages.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def wait(text):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = messages.get(timeout=max(.1, deadline - time.monotonic()))
            assert line is not None, ''.join(lines)
            assert not any(bad in line for bad in ("PANIC", "SIGSEGV", "app forced stop")), line
            if text in line:
                return
        raise TimeoutError(text)

    def key(code):
        for value in (1, 0):
            os.write(fd, struct.pack('llHHi', 0, 0, 1, code, value))
        time.sleep(.3)

    def shot(number):
        source = Path(f"/tmp/qos-shell-{number}.ppm")
        # Main's default runWindow tag is qos-shell. Never accept a stale capture.
        assert not source.exists(), f"old capture: {source}"
        key(4025)
        wait(f"shell: snapshot {number}")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if source.exists():
                data = source.read_bytes()
                parts = data.split(b"\n", 3)
                if len(parts) == 4 and parts[0] == b"P6" and parts[2] == b"255":
                    width, height = map(int, parts[1].split())
                    if len(parts[3]) == width * height * 3:
                        destination = out / f"counter-{number}.ppm"
                        shutil.move(source, destination)
                        return data
            time.sleep(.1)
        raise TimeoutError(str(source))

    try:
        wait("shell: Main Profile ready (12 shortcuts")
        # A running Main owns the same lock the installer needs.
        attempt = subprocess.run(guard + [str(prefix / "bin/qos"), "install",
            str(out / "renamed project/build/counter-example.qa"), str(disk)],
            cwd=out, env=env, capture_output=True, text=True, timeout=30)
        (out / "in-use-refusal.log").write_text(attempt.stdout + attempt.stderr)
        assert attempt.returncode == 1 and "disk is in use" in attempt.stderr, attempt
        # Six onboard apps follow four builtin shortcuts; counter is index 10.
        key(107)
        key(105)
        key(28)
        wait("shell: open counter-example")
        time.sleep(.5)
        before = shot(1)
        key(57)
        after = shot(2)
        assert before != after, "counter key did not change the rendered frame"
        key(1)
        wait("shell: home")
        key(16)
        proc.wait(timeout=20)
        assert proc.returncode == 0, ''.join(lines)
        assert not any(bad in ''.join(lines) for bad in ("app forced stop", "shutdown failed", "cleanup unconfirmed"))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        thread.join(timeout=2)
        os.close(fd)
        (out / "main.log").write_text(''.join(lines))


if __name__ == "__main__":
    main()
