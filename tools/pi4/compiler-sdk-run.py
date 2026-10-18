#!/usr/bin/env python3
"""Runtime for a relocatable, native Pi Editor SDK; no build-host paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent


def environment(work):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    temporary = work / "tmp"
    temporary.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update(FPRISC_ROOT=str(ROOT / "fprisc"),
               FPR_HOME=str(ROOT / "qos"), FPR_PATH=str(ROOT / "fprisc"),
               FPR_FOREIGN=str(ROOT / "qos/core/foreign.fpr"),
               FPRD_BUILD=str(work / "build"), TMPDIR=str(temporary),
               XDG_CACHE_HOME=str(work / "cache"),
               # Built with -rtsopts: bound live managed heap and stack. The
               # large GHC virtual reservation is not resident application data.
               GHCRTS="-M512m -K64m",
               PATH=str(ROOT / "bin") + ":/usr/bin:/bin",
               # gcc only assembles native .s files and invokes collect2/ld;
               # never a cc1 frontend, headers, C runtime, or system library.
               COMPILER_PATH=str(ROOT / "bin"),
               PLUG_A64_LINK="gcc -fno-use-linker-plugin -nostdlib -nostartfiles -static -no-pie "
               "-Wl,--build-id=none -Wl,-z,noexecstack -Wl,--no-relax "
               "-T $(QOS)/appside/link-qosplug.ld -Wl,--emit-relocs",
               LC_ALL="C.UTF-8")
    return env


def request(sock, profile, source):
    payload = profile.encode() + b"\n" + source
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(440)
        client.connect(sock)
        client.sendall(struct.pack("<I", len(payload)) + payload)
        def exact(n):
            result = bytearray()
            while len(result) < n:
                data = client.recv(n - len(result))
                if not data:
                    raise RuntimeError("compiler socket closed early")
                result.extend(data)
            return bytes(result)
        size, = struct.unpack("<I", exact(4))
        if size > 32 << 20:
            raise RuntimeError("compiler reply exceeds 32 MiB")
        return exact(size)


def spawn(sock, work, log=None):
    return subprocess.Popen([sys.executable, "-S", str(ROOT / "qos/tools/fprd.py"), sock],
                            cwd=ROOT / "qos", env=environment(work), stdout=log, stderr=log)


def ready(child, sock):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"compiler daemon exited: {child.returncode}")
        try:
            if request(sock, "unknown", b"").startswith(b"err\nunknown profile"):
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(.05)
    raise RuntimeError("compiler socket did not become ready")


def selftest():
    # Run through the wire protocol and actual make/assembler/link/QA path.
    # The native application loader is verified separately on the device.
    manifest = json.loads((ROOT / "sdk.json").read_text())
    compiler_hash = hashlib.sha256((ROOT / "fprisc/fpr").read_bytes()).hexdigest()
    if manifest["compiler_sha256"] != compiler_hash:
        raise RuntimeError("packaged compiler digest does not match SDK manifest")
    with tempfile.TemporaryDirectory(prefix="fpr-sdk-test-") as td:
        sock = str(Path(td) / "compiler.sock")
        with (Path(td) / "daemon.log").open("w+") as log:
            child = spawn(sock, td, log)
            try:
                ready(child, sock)
                source = (b'A = use "std/actor#201a0e9bf98a5154".\n'
                          b'add a b = a + b.\nmain = "native Pi SDK".\n')
                checked = request(sock, "check", source)
                if checked != b"ok\n":
                    raise RuntimeError("check failed: " + checked.decode(errors="replace"))
                packaged = request(sock, "plugin:0:sdkprobe", source)
                if not packaged.startswith(b"ok\nQAR2\n"):
                    raise RuntimeError("plugin failed: " + packaged[:8192].decode(errors="replace"))
                publication = request(sock, "publication:sdkpub", source)
                if not publication.startswith(b"ok\n"):
                    raise RuntimeError("publication failed: " + publication[:8192].decode(errors="replace"))
                header, image = publication[3:].split(b"\n", 1)
                fields = header.split(b"\t")
                if len(fields) != 3 or fields[0] != b"sdkpub" or len(fields[2]) != 16 or not image.startswith(b"QAR2\n"):
                    raise RuntimeError("invalid frozen publication")
                repeated = request(sock, "publication:sdkpub", source)
                if repeated != publication:
                    raise RuntimeError("unchanged publication was not stable: " + repeated[:8192].decode(errors="replace"))
                changed = request(sock, "publication:sdkpub", source.replace(b"a + b.", b"a + b + 1."))
                if not changed.startswith(b"ok\n"):
                    raise RuntimeError("publication update failed: " + changed[:8192].decode(errors="replace"))
                changed_header, changed_image = changed[3:].split(b"\n", 1)
                changed_fields = changed_header.split(b"\t")
                if changed_fields[:2] != [b"sdkpub", b"v1.1"] or changed_fields[2] == fields[2] or not changed_image.startswith(b"QAR2\n"):
                    raise RuntimeError("publication update lost immutable version identity")
                bad = request(sock, "check", b"main = syntax @@@.\n")
                if not bad.startswith(b"err\n"):
                    raise RuntimeError("invalid source was accepted")
                print(json.dumps({"check": "ok", "plugin": "QAR2", "plugin_bytes": len(packaged) - 3,
                                  "compiler_sha256": compiler_hash,
                                  "publication": "committed-frozen-stable-updated", "publication_version": changed_fields[1].decode(),
                                  "invalid_source": "refused", "target": "native-aarch64"}))
            finally:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                if child.returncode not in (0, -signal.SIGTERM):
                    log.seek(0)
                    print(log.read(), file=sys.stderr)


def daemon(sock, work):
    child = spawn(sock, work)
    stopping = False
    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True
        child.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        try:
            ready(child, sock)
        except RuntimeError:
            if not stopping:
                raise
        if not stopping and os.environ.get("QOSP_READY_FILE"):
            Path(os.environ["QOSP_READY_FILE"]).write_text(str(os.getpid()) + "\n")
        status = child.wait()
        # The standard supervisor requires an acknowledged administrative
        # stop to exit successfully. Unexpected daemon death must still fail.
        return 0 if stopping and status in (0, -signal.SIGTERM, -signal.SIGINT) else status
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        Path(sock).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("daemon", "selftest"))
    ap.add_argument("--socket", default=os.environ.get("FPRD_SOCK", "/tmp/fprd.sock"))
    ap.add_argument("--work", default=os.environ.get("FPRD_WORK", "/run/fpr-sdk-work"))
    args = ap.parse_args()
    if args.command == "selftest":
        selftest()
        return 0
    return daemon(args.socket, args.work)


if __name__ == "__main__":
    sys.exit(main())
