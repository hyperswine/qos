#!/usr/bin/env python3
"""Isolated SDK service configuration/refusal tests; never mounts or stops QOS."""
import hashlib
import gzip
import io
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]


def executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


def wrapper_stop_check(base, startup=False, unexpected=False):
    """Fork the real wrapper with a live fake daemon; signal actual processes."""
    case = base / ("wrapper-" + ("unexpected" if unexpected else "startup" if startup else "stop"))
    case.mkdir()
    wrapper = os.fork()
    if wrapper == 0:
        os.setsid()
        try:
            spec = importlib.util.spec_from_file_location("sdk_wrapper_check", ROOT / "tools/pi4/compiler-sdk-run.py")
            runtime = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runtime)
            os.environ.pop("QOSP_READY_FILE", None)
            def fake_spawn(_sock, _work):
                child = subprocess.Popen([shutil.which("sleep"), "60"])
                (case / "daemon.pid").write_text(str(child.pid))
                return child
            def fake_ready(child, _sock):
                (case / "entered").touch()
                if startup:
                    while child.poll() is None:
                        time.sleep(.01)
                    raise RuntimeError("daemon ended during startup")
            runtime.spawn, runtime.ready = fake_spawn, fake_ready
            status = runtime.daemon(str(case / "compiler.sock"), case)
            os._exit(status & 255)
        except BaseException:
            os._exit(2)
    try:
        deadline = time.monotonic() + 5
        while not (case / "entered").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (case / "entered").exists(), "wrapper did not enter readiness"
        child_pid = int((case / "daemon.pid").read_text())
        if unexpected:
            os.kill(child_pid, signal.SIGTERM)
        else:
            # The production supervisor signals this owned process group.
            os.killpg(wrapper, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            done, status = os.waitpid(wrapper, os.WNOHANG)
            if done:
                code = os.waitstatus_to_exitcode(status)
                assert code == (241 if unexpected else 0), (startup, unexpected, code)
                break
            time.sleep(.01)
        else:
            raise AssertionError("wrapper did not stop within five seconds")
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("wrapper left its fake daemon alive")
    finally:
        try:
            os.killpg(wrapper, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main():
    with tempfile.TemporaryDirectory(prefix="fpr-sdk-service-", dir="/tmp") as td:
        base = Path(td)
        bins = base / "bin"
        bins.mkdir()
        archive = base / "compiler-sdk.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name, data, mode in (("bin/qos-fprd", b"#!/bin/sh\nexit 0\n", 0o755),
                                     ("sdk.json", b"{}\n", 0o644)):
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode = len(data), mode
                tar.addfile(entry, io.BytesIO(data))
        archive.with_suffix(".gz.sha256").write_text(
            hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")
        executable(bins / "mount", '#!/bin/sh\nprintf "%s\\n" "$*" >> "$SDK_TEST_MOUNTS"\n')
        sha = shutil.which("sha256sum") or shutil.which("gsha256sum")
        if not sha:
            raise SystemExit("test requires sha256sum or gsha256sum")
        (bins / "sha256sum").symlink_to(sha)
        guard = bins / "guard"
        executable(guard, '#!/bin/sh\nshift\nexport QOSP_SERVICE_GUARDED=1\nexec "$@"\n')
        control = bins / "control"
        executable(control, f'''#!{sys.executable}
import json, os, pathlib, sys
base=pathlib.Path(os.environ['SDK_TEST_ROOT'])
with (base/'calls').open('a') as f:
    f.write(json.dumps(dict(command=sys.argv[1],guarded=os.environ.get('QOSP_SERVICE_GUARDED'),
        run=os.environ['QOSP_RUN_DIR'],config=os.environ['QOSP_CONFIG'],
        session=os.environ['QOSP_SESSION'],socket=os.environ['FPRD_SOCK']))+'\\n')
state=base/'running'
if sys.argv[1]=='status': sys.exit(0 if state.exists() else 3)
if sys.argv[1]=='start': state.touch()
if sys.argv[1]=='stop':
    if os.environ.get('SDK_TEST_FAIL_STOP'): sys.exit(1)
    state.unlink(missing_ok=True)
''')
        env = dict(os.environ, PATH=str(bins) + ":" + os.environ["PATH"],
                   FPRD_CONFIG="/dev/null", FPRD_ARCHIVE=str(archive),
                   FPRD_SDK_RAM=str(base / "sdk"), FPRD_WORK=str(base / "work"),
                   FPRD_RUN_DIR=str(base / "service"), FPRD_CONTROL=str(control),
                   QOSP_SERVICE_GUARD=str(guard), SDK_TEST_ROOT=str(base),
                   SDK_TEST_MOUNTS=str(base / "mounts"))
        script = ROOT / "tools/pi4/S98fprd"
        def invoke(command, expected=0, extra=None):
            result = subprocess.run(["sh", str(script), command], env=dict(env, **(extra or {})),
                                    text=True, capture_output=True)
            if result.returncode != expected:
                raise AssertionError((command, result.returncode, result.stdout, result.stderr))
        invoke("start")
        sdk = base / "sdk/root"
        assert (sdk / "sdk.json").is_file()
        calls = [json.loads(line) for line in (base / "calls").read_text().splitlines()]
        assert all(call["guarded"] == "" for call in calls), calls
        assert all(call["run"] == str(base / "service") and call["config"] == "/dev/null"
                   and call["socket"] == "/tmp/fprd.sock" for call in calls), calls
        mounts = (base / "mounts").read_text()
        assert "size=192m,nodev,nosuid" in mounts and "size=128m,nodev,nosuid" in mounts
        marker = sdk / "preserve"
        marker.touch()
        invoke("start")
        assert marker.exists(), "idempotent start replaced a running SDK"
        invoke("stop")
        archive.with_suffix(".gz.sha256").write_text("0" * 64 + "  " + archive.name + "\n")
        invoke("start", expected=1)
        assert marker.exists(), "checksum failure modified the previous SDK"
        for corrupt in (b"not gzip", gzip.compress(b"not a tar archive")):
            archive.write_bytes(corrupt)
            archive.with_suffix(".gz.sha256").write_text(
                hashlib.sha256(corrupt).hexdigest() + "  " + archive.name + "\n")
            invoke("start", expected=1)
            assert marker.exists(), "decompression/extraction failure modified the previous SDK"
            assert not list((base / "sdk").glob("archive.*.tar")), "failed extraction leaked its tar"
        lib = base / "service.sh"
        lib.write_text('qosp_config() { :; }\nqosp_recorded() { return 0; }\nqosp_child_uncertain() { return 0; }\n')
        invoke("restart", expected=1, extra={"SDK_TEST_FAIL_STOP": "1", "QOSP_SERVICE_LIB": str(lib)})
        assert marker.exists(), "failed stop modified the live SDK"
        # The immutable store fallback must preserve path-based library trust
        # without trusting edited copies, deleting roots, or writing the SDK.
        os.environ["FPRISC_ROOT"] = str(base / "compiler")
        spec = importlib.util.spec_from_file_location("fprd_sdk_check", ROOT / "tools/fprd.py")
        daemon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(daemon)
        shipped = base / "shipped/.fpr/store"
        private = base / "publication/.fpr/store"
        shipped.mkdir(parents=True)
        private.mkdir(parents=True)
        for name in ("a", "b", "c"):
            (shipped / (name * 16 + ".fpr")).write_text("approved dependency")
            (private / (name * 16 + ".fpr")).write_text("approved dependency")
        (private / ("c" * 16 + ".fpr")).write_text("edited dependency")
        (base / "publication/.fpr/versions.db").write_text("module v1.0 " + "b" * 16 + "\n")
        os.environ["FPR_HOME"] = str(base / "shipped")
        daemon.prefer_shipped_dependencies(base / "publication")
        assert not (private / ("a" * 16 + ".fpr")).exists()
        assert (private / ("b" * 16 + ".fpr")).read_text() == "approved dependency"
        assert (private / ("c" * 16 + ".fpr")).read_text() == "edited dependency"
        assert all(path.read_text() == "approved dependency" for path in shipped.glob("*.fpr"))
        wrapper_stop_check(base)
        wrapper_stop_check(base, startup=True)
        wrapper_stop_check(base, unexpected=True)
        print("SDK service checks passed: isolated ownership, nested guards, RAM bounds, idempotency, checksum/gzip/tar/stop refusal")
        print("Publication store checks passed: shipped dependency fallback, private roots, changed copies, immutable SDK")
        print("Actual wrapper signal checks passed: clean stop, startup cancellation, unexpected daemon death stays failed")


if __name__ == "__main__":
    main()
