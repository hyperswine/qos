#!/usr/bin/env python3
"""tools/fprd.py's socket hardening (review I-9).

  - the socket is created 0600 (this user only);
  - a path that is not this user's socket (a regular file here) is refused,
    not unlinked and replaced;
  - a client that stalls mid-frame is dropped after the connection timeout
    instead of wedging every later request;
  - qos/portable/compile.c checks the server's uid by peer credentials
    (covered by qos/tests-host/compile-check.sh still passing as this user).
"""
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, FPRD_CONN_TIMEOUT_S='1')
ENV.setdefault('FPRISC_ROOT', str(ROOT.parent / 'fprisc'))


def start(path):
    p = subprocess.Popen([sys.executable, str(ROOT / 'tools/fprd.py'), str(path)], env=ENV,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p


with tempfile.TemporaryDirectory(prefix='qos-fprd-') as name:
    tmp = Path(name)
    # a regular file at the path: refused, left alone
    squat = tmp / 'squat.sock'
    squat.write_text('not a socket')
    p = start(squat)
    out, _ = p.communicate(timeout=30)
    assert p.returncode != 0 and 'refusing to replace it' in out, (p.returncode, out)
    assert squat.read_text() == 'not a socket'
    print('fprd: a non-socket at the path is refused, not replaced: PASS', flush=True)

    path = tmp / 'fprd.sock'
    p = start(path)
    try:
        deadline = time.monotonic() + 30
        while not path.exists():
            assert p.poll() is None and time.monotonic() < deadline, p.stdout.read() if p.poll() is not None else 'no socket'
            time.sleep(0.05)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600, oct(mode)
        print('fprd: socket is 0600: PASS', flush=True)

        stalled = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stalled.connect(str(path))
        stalled.sendall(b'\x10\x00')  # half a length prefix, then nothing
        start_t = time.monotonic()
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(20)
        c.connect(str(path))
        c.sendall(struct.pack('<I', 0xFFFFFFFF))  # too large: answered without compiling
        n = struct.unpack('<I', c.recv(4))[0]
        reply = b''
        while len(reply) < n:
            reply += c.recv(n - len(reply))
        waited = time.monotonic() - start_t
        assert reply == b'err\nrequest too large', reply
        assert waited < 10, waited
        stalled.close(); c.close()
        print(f'fprd: a stalled client is dropped; the next request answered after {waited:.1f}s: PASS', flush=True)
    finally:
        p.terminate()
        p.wait(timeout=10)
print('fprd-hardening: PASS')
