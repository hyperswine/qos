#!/usr/bin/env python3
"""server-check.py -- drive an FP-RISC server running in the FreeBSD guest.

The same websocket client qos/tests-host/liveboard-check.py uses, pointed at
a binary that was CROSS-BUILT for FreeBSD and is running there.  It runs on
the host rather than in the guest deliberately: the guest keeps exactly the
packages a stock release image ships with, which is the claim being tested --
that an FP-RISC server needs a libc and nothing else.

The guest's server binds 127.0.0.1, which QEMU's user networking cannot
reach, so the connection goes through an ssh tunnel -- ssh runs inside the
guest and can.

  ./server-check.py [sessions]        default 50

  QOS_BSD_BINARY   the server in the guest (default ~/liveboard-freebsd)
"""
import base64, json, os, socket, struct, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.environ.get("QOS_BSD_DIR", os.path.expanduser("~/.cache/qos-freebsd-vm"))
SSH_PORT = os.environ.get("QOS_BSD_PORT", "2224")
BIN = os.environ.get("QOS_BSD_BINARY", "~/liveboard-freebsd")
MANY = int(sys.argv[1]) if len(sys.argv) > 1 else 50
RPORT = 8080          # in the guest
LPORT = 18080         # on this machine, through the tunnel

SSH = ["ssh", "-i", f"{DIR}/id_vm", "-p", SSH_PORT,
       "-o", "StrictHostKeyChecking=no",
       "-o", f"UserKnownHostsFile={DIR}/known_hosts",
       "-o", "LogLevel=ERROR", "dev@127.0.0.1"]


def guest(cmd, timeout=120):
    return subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)


def fail(msg, extra=""):
    print(f"server-check: FAIL: {msg}")
    if extra:
        print(extra.rstrip()[-2000:])
    raise SystemExit(1)


class Ws:
    """The page's own protocol, exactly as liveboard-check.py speaks it."""

    def __init__(self, port, timeout=30):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(
            f"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            d = self.s.recv(4096)
            if not d:
                raise EOFError("closed during the handshake")
            self.buf += d
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        assert b"101" in head.split(b"\r\n")[0], head

    def send(self, name, *fields, arg=None, raw=None):
        wire = raw if raw is not None else \
            ("+" if arg is not None else "=") + json.dumps([name, *map(str, fields)])
        p = json.dumps({"msg": wire, "arg": arg or ""}).encode()
        mask = os.urandom(4)
        hdr = (bytes([0x81, 0x80 | len(p)]) if len(p) < 126 else
               bytes([0x81, 0x80 | 126]) + struct.pack(">H", len(p)) if len(p) < 65536 else
               bytes([0x81, 0x80 | 127]) + struct.pack(">Q", len(p)))
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(p)))

    def need(self, n):
        while len(self.buf) < n:
            d = self.s.recv(65536)
            if not d:
                raise EOFError
            self.buf += d

    def recv(self, timeout=30):
        self.s.settimeout(timeout)
        self.need(2)
        op, n = self.buf[0] & 15, self.buf[1] & 127
        off = 2
        if n == 126:
            self.need(4); n = struct.unpack(">H", self.buf[2:4])[0]; off = 4
        elif n == 127:
            self.need(10); n = struct.unpack(">Q", self.buf[2:10])[0]; off = 10
        self.need(off + n)
        p, self.buf = self.buf[off:off + n], self.buf[off + n:]
        return ("close", p) if op == 8 else json.loads(p)

    def until(self, pred, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            if pred(self.recv(max(0.1, end - time.time()))):
                return True
        raise TimeoutError


def has(m, text):
    return isinstance(m, dict) and text in json.dumps(m)


def main():
    import urllib.request

    guest(f"kill $(cat /tmp/sc.pid) 2>/dev/null; rm -f /tmp/sc.pid /tmp/sc.log /tmp/sc.kvlog")
    r = guest(f"daemon -f -p /tmp/sc.pid -o /tmp/sc.log {BIN} "
              f"--port={RPORT} --store=/tmp/sc.kvlog")
    if r.returncode != 0:
        fail("could not start the server in the guest", r.stderr)
    for _ in range(80):
        if "ready" in guest("cat /tmp/sc.log 2>/dev/null").stdout:
            break
        time.sleep(0.25)
    else:
        fail("the server never said 'ready'", guest("cat /tmp/sc.log").stdout)
    print(f"server-check: started in the guest ({guest('uname -sr').stdout.strip()})")

    tun = subprocess.Popen(SSH[:-1] + ["-N", "-L", f"{LPORT}:127.0.0.1:{RPORT}", SSH[-1]],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    conns = []
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", LPORT), timeout=1).close()
                break
            except OSError:
                time.sleep(0.25)
        else:
            fail("the ssh tunnel never opened")

        page = urllib.request.urlopen(f"http://127.0.0.1:{LPORT}/", timeout=30).read().decode()
        for marker in ('id="lv-root"', "window.__LV__", "new WebSocket", ".col"):
            if marker not in page:
                fail(f"the served page has no {marker}")
        print(f"server-check: page served, {len(page)} bytes "
              "(generated CSS, the seed, the client script)")

        a, b = Ws(LPORT), Ws(LPORT)
        conns += [a, b]
        fa, fb = a.recv(), b.recv()
        if "session 1" not in "".join(fa["s"]) or "session 2" not in "".join(fb["s"]):
            fail("the two sessions did not each get their own view", json.dumps(fa)[:500])
        nstat, ndyn = len(fa["s"]), len(fa["d"])
        a.send("Bump", 10)
        a.until(lambda m: has(m, '"10"'))
        b.until(lambda m: has(m, '"10"'))
        print(f"server-check: two sessions, one shared model; an update reaches both "
              f"as a delta ({nstat} statics, {ndyn} dynamics)")

        a.send("Add", arg="a note from the host")
        b.until(lambda m: has(m, "a note from the host"))
        print("server-check: an event carrying client state reached the model")

        for forged in ['=["Nope"]', '=["Bump","ten"]', '=["Bump"]', "bump", "=not json"]:
            a.send("", raw=forged)
        a.send("Bump", 1)
        a.until(lambda m: has(m, '"11"'))
        print("server-check: malformed and unknown messages refused; the session survived")

        a.send("Clock")
        a.until(lambda m: has(m, "1 s"))
        a.until(lambda m: has(m, "2 s"))
        a.send("Clock")
        print("server-check: a subscription ticked and stopped")

        a.send("Hash")
        a.until(lambda m: has(m, "working"))
        a.until(lambda m: has(m, "digest ready"))
        print("server-check: a command ran in its own actor and returned as an event")

        t0 = time.time()
        many = [Ws(LPORT) for _ in range(MANY)]
        conns += many
        for w in many:
            w.recv()
        opened = time.time() - t0
        a.send("Bump", 5)
        for w in many:
            w.until(lambda m: has(m, '"16"'))
        print(f"server-check: {MANY} concurrent sessions opened in {opened:.1f}s; "
              "all saw the next update")

        size = guest("stat -f %z /tmp/sc.kvlog 2>/dev/null || echo 0").stdout.strip()
        if not size.isdigit() or int(size) == 0:
            fail("the append-only store was never written")
        print(f"server-check: durable store written in the guest ({size} bytes)")

        print("server-check: PASS")
    finally:
        for w in conns:
            try:
                w.s.close()
            except OSError:
                pass
        tun.terminate()
        guest("kill $(cat /tmp/sc.pid) 2>/dev/null; true")


if __name__ == "__main__":
    main()
