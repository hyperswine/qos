#!/usr/bin/env python3
"""fprd.py -- the fpr compiler hosted as a UNIX-DOMAIN-SOCKET server.

QOS Portable apps reach it through Sys.compile (std/compile.fpr):
the app-side shim rides the qosp syscall channel (tag 7), qosp's
host side (qos/portable/compile.c) connects HERE, and this daemon
runs the actual ./fprc pipeline -- so the compiler stays a host
process while the editing/storing policy stays inside QOS.

    cd fp-risc && python3 tools/fprd.py [sock-path]

  socket   argv[1], else $FPRD_SOCK, else /tmp/fprd.sock
  frame    4-byte LE length + payload, both directions
  request  "<profile>\n<source bytes>" -- profile is a WHITELISTED
           token (never argv passthrough): qos-portable | bare-metal
           | plugin:<slot>:<id>  (slot 0..7, id [a-z][a-z0-9_]{0,15})
  reply    "ok\n<assembly .s text>"  or  "err\n<compiler stderr>"

The plugin form is the PACKAGE op: the source is built as a
hot-loadable module .qa -- the same `make plugin-qa` mechanics the
livereload harness uses (fprc --plugin, a relocatable link whose
runtime imports bind by name, mkqa) -- and the reply carries the .qa
BYTES.  With it, a running QOS app closes the loop entirely from
inside: edit source, CP.plugin it, append the bytes to its qlog store,
LR.load them through the compat gate, hot-swap.  The <slot> in the
token is accepted and ignored: a plugin is placed wherever the app's
heap has room (docs/2026-10-01-IMPORT-TABLE.md).

One connection per compile, requests served sequentially (fprc is a
process spawn; the client holds one syscall anyway).  The reply is
the PROGRAM's own .s; module units (e.g. the prelude) are shared
cached artifacts on the host side and do not ride the channel.
"""
import os
import platform
import re
import socket
import struct
import subprocess
import sys
import tempfile

FPRISC_ROOT = os.environ.get("FPRISC_ROOT")
if not FPRISC_ROOT:
    sys.exit("fprd: set FPRISC_ROOT to the fprisc checkout")
COMPILER = os.path.join(FPRISC_ROOT, "fpr")
os.environ["FPR_HOME"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["FPR_PATH"] = FPRISC_ROOT
os.environ["FPR_FOREIGN"] = os.path.join(os.environ["FPR_HOME"], "core", "foreign.fpr")

PROFILES = {"qos-portable", "bare-metal"}
PLUGIN_RE = re.compile(r"^plugin:([0-7]):([a-z][a-z0-9_]{0,15})$")
MAX_REQ = 4 << 20  # a 4 MiB source bound: honest refusal, not an OOM


def recv_exact(c, n):
    buf = b""
    while len(buf) < n:
        part = c.recv(n - len(buf))
        if not part:
            raise ConnectionError("peer closed mid-frame")
        buf += part
    return buf


def package_plugin(slot, plugid, source):
    """The package op: source -> a linked, mkqa-wrapped relocatable
    plugin .qa, via the plugin-qa make target (so the unit objects, link
    script, and manifest mechanics stay in ONE place).  Requests are
    served sequentially, so the per-id paths cannot race.  The slot is
    the old protocol's and is ignored: the plugin is bound to no address
    and to no shell build (its runtime imports resolve by name)."""
    # intermediates go where the caller's run keeps them (qos.py passes
    # its workspace build dir); a bare `fprd.py` from fp-risc/ uses build/
    bdir = os.environ.get("FPRD_BUILD", "build")
    os.makedirs(os.path.join(bdir, "fprd-src"), exist_ok=True)
    src = os.path.join(bdir, "fprd-src", plugid + ".fpr")
    with open(src, "wb") as f:
        f.write(source)
    target = "plugin-qa"  # qos-app.mk picks the image this host's qosp runs
    env = dict(os.environ, LC_ALL="C.UTF-8")
    r = subprocess.run(
        ["make", "-s", target, "PROG=" + src],
        capture_output=True, env=env, timeout=300)
    qa = plugid + ".qa"
    if r.returncode != 0 or not os.path.exists(qa):
        msg = (r.stderr + r.stdout).strip() or b"plugin build failed"
        return b"err\n" + msg
    with open(qa, "rb") as f:
        return b"ok\n" + f.read()


def compile_one(profile, source):
    m = PLUGIN_RE.match(profile)
    if m:
        return package_plugin(int(m.group(1)), m.group(2), source)
    if profile not in PROFILES:
        # NB: bytes %-formatting refuses str args -- the old %r here THREW,
        # and an exception in compile_one killed the whole serve loop
        return ("err\nunknown profile %r (want: %s | plugin:<slot>:<id>)" % (
            profile, " | ".join(sorted(PROFILES)))).encode()
    with tempfile.TemporaryDirectory(prefix="fprd-") as td:
        src = os.path.join(td, "in.fpr")
        out = os.path.join(td, "out.s")
        with open(src, "wb") as f:
            f.write(source)
        env = dict(os.environ, LC_ALL="C.UTF-8")
        r = subprocess.run(
            [COMPILER, "--profile=" + profile, "--prelude=" + os.path.join(FPRISC_ROOT, "core/prelude.fpr"),
             src, out],
            capture_output=True, env=env, timeout=120)
        if r.returncode != 0 or not os.path.exists(out):
            msg = (r.stderr + r.stdout).strip() or b"compile failed"
            return b"err\n" + msg
        with open(out, "rb") as f:
            return b"ok\n" + f.read()


def serve(path):
    if not os.path.exists(COMPILER):
        sys.exit("fprd: build the compiler at FPRISC_ROOT first")
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)
    print(f"fprd: serving ./fprc on {path}", flush=True)
    while True:
        c, _ = srv.accept()
        try:
            (n,) = struct.unpack("<I", recv_exact(c, 4))
            if n > MAX_REQ:
                reply = b"err\nrequest too large"
            else:
                req = recv_exact(c, n)
                nl = req.find(b"\n")
                profile = req[:nl].decode("ascii", "replace") if nl >= 0 else ""
                source = req[nl + 1:] if nl >= 0 else b""
                try:
                    reply = compile_one(profile, source)
                except subprocess.TimeoutExpired:
                    reply = b"err\ncompile timed out"
            c.sendall(struct.pack("<I", len(reply)) + reply)
        except (ConnectionError, OSError) as e:
            print(f"fprd: connection dropped: {e}", flush=True)
        finally:
            c.close()


if __name__ == "__main__":
    serve(sys.argv[1] if len(sys.argv) > 1
          else os.environ.get("FPRD_SOCK", "/tmp/fprd.sock"))
