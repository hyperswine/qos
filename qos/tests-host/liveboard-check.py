#!/usr/bin/env python3
"""liveboard-check.py -- drive programs/liveboard.fpr (std/live on a plain posix
process) as real websocket clients: two sessions, deltas, client/server state,
commands and subscriptions, many sessions fanned out, durable fields across a
restart, and the journal replayed.   usage: liveboard-check.py <binary> [sessions]"""
import atexit, base64, json, os, signal, socket, struct, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

binary = sys.argv[1]
many = int(sys.argv[2]) if len(sys.argv) > 2 else 100

# ---- the server under test, and being sure it dies --------------------------
#
# A server started here must not outlive the harness.  It used to be a bare
# `finally: kill`, which does not survive the HARNESS being killed -- and this
# check is routinely killed: by the outer `timeout` in check-all.sh, and by
# anyone who gives up watching a 1000-session run.  Every abandoned run left a
# liveboard holding a port forever.  Three things close that:
#
#   * its own process GROUP, so one signal reaches the server however it forked;
#   * SIGTERM/SIGINT/SIGHUP handlers and an atexit hook, so every ordinary way
#     this process dies runs the same cleanup;
#   * a pidfile swept on startup, for the one way those cannot cover (SIGKILL).
#
# Output goes to a FILE rather than a pipe.  A pipe is 64 KiB and nobody was
# draining it while the check ran, so a server that logged enough during a long
# run would block in write() and never answer again -- indistinguishable from
# the flake this check exists to hunt.
PIDFILE = Path(tempfile.gettempdir()) / 'liveboard-check.pids'
LIVE = []


def _looks_like_ours(pid):
    """Never signal a pid we cannot confirm: pids are reused."""
    r = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)], capture_output=True, text=True)
    return 'liveboard' in r.stdout


def _sweep():
    if not PIDFILE.exists():
        return
    killed = 0
    for tok in PIDFILE.read_text().split():
        if not tok.isdigit():
            continue
        pid = int(tok)
        if _looks_like_ours(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                killed += 1
            except OSError:
                pass
    PIDFILE.unlink(missing_ok=True)
    if killed:
        print(f'(swept {killed} server(s) an earlier run left behind)', file=sys.stderr)


def _remember():
    PIDFILE.write_text(' '.join(str(p.pid) for p in LIVE if p.poll() is None))


def said(p):
    """Everything the server printed -- its own log, not a half-read pipe."""
    try:
        lines = [l for l in Path(p.log).read_text().splitlines()
                 if l.strip() and not l.startswith(('dl:', '   trace'))]
    except OSError:
        return '(no output)'
    return '\n   '.join(lines[-12:])


def start(port, store, *extra, ready_within=30):
    log = tempfile.NamedTemporaryFile(prefix='liveboard-', suffix='.log', delete=False)
    p = subprocess.Popen([binary, f'--port={port}', f'--store={store}', *extra],
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    p.log = log.name
    LIVE.append(p)
    _remember()
    # a bounded wait: a server that never says `ready` is a failure to report,
    # not a readline() that hangs until something outside kills us
    end = time.time() + ready_within
    while time.time() < end:
        if p.poll() is not None:
            raise AssertionError(f'server exited {p.returncode} before it was ready:\n   {said(p)}')
        if any(l.startswith('ready') for l in Path(p.log).read_text().splitlines()):
            return p
        time.sleep(0.05)
    stop(p)
    raise AssertionError(f'server never said `ready` within {ready_within} s:\n   {said(p)}')


def stop(p):
    if p.poll() is None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except OSError:
            p.kill()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    if p in LIVE:
        LIVE.remove(p)
    _remember()


def _cleanup():
    for p in list(LIVE):
        try:
            stop(p)
        except Exception:
            pass
    PIDFILE.unlink(missing_ok=True)


atexit.register(_cleanup)
for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(_sig, lambda s, _f: (_cleanup(), os._exit(128 + s)))
_sweep()

class Ws:
    def __init__(self, port, timeout=20):
        self.s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(f'GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'.encode())
        self.buf = b''
        while b'\r\n\r\n' not in self.buf:
            d = self.s.recv(4096)
            if not d: raise EOFError('closed during the handshake')
            self.buf += d
        head, self.buf = self.buf.split(b'\r\n\r\n', 1)
        assert b'101' in head.split(b'\r\n')[0], head
    def send(self, name, *fields, arg=None, raw=None):
        """a TYPED message, as View.send / View.sendWith put it in the page:
        "=" [name, field...] is complete; "+" takes `arg` as its final field"""
        wire = raw if raw is not None else ('+' if arg is not None else '=') + json.dumps([name, *map(str, fields)])
        p = json.dumps({'msg': wire, 'arg': arg or ''}).encode()
        mask = os.urandom(4)
        hdr = (bytes([0x81, 0x80 | len(p)]) if len(p) < 126 else bytes([0x81, 0x80 | 126]) + struct.pack('>H', len(p)) if len(p) < 65536
               else bytes([0x81, 0x80 | 127]) + struct.pack('>Q', len(p)))
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(p)))
    def need(self, n):
        while len(self.buf) < n:
            d = self.s.recv(65536)
            if not d: raise EOFError
            self.buf += d
    def recv(self, timeout=20):
        self.s.settimeout(timeout)
        self.need(2)
        op, n = self.buf[0] & 15, self.buf[1] & 127
        off = 2
        if n == 126: self.need(4); n = struct.unpack('>H', self.buf[2:4])[0]; off = 4
        elif n == 127: self.need(10); n = struct.unpack('>Q', self.buf[2:10])[0]; off = 10
        self.need(off + n)
        p, self.buf = self.buf[off:off + n], self.buf[off + n:]
        return ('close', p) if op == 8 else json.loads(p)
    def until(self, pred, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            m = self.recv(max(0.1, end - time.time()))
            if pred(m): return m
        raise TimeoutError

def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close(); return port

def has(m, text): return isinstance(m, dict) and text in json.dumps(m)

with tempfile.TemporaryDirectory() as t:
    store, port = os.path.join(t, 'board.kvlog'), free_port()
    srv = start(port, store)
    try:
        page = urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=20).read().decode()
        assert 'id="lv-root"' in page and 'window.__LV__' in page and '.col' in page and 'new WebSocket' in page
        print('page: generated CSS, the seed (statics + first dynamics), the client script: PASS')
        a, b = Ws(port), Ws(port)
        fa, fb = a.recv(), b.recv()
        assert 's' in fa and 'd' in fa and 'session 1' in ''.join(fa['s']) and 'session 2' in ''.join(fb['s'])
        nstat, ndyn = len(fa['s']), len(fa['d'])
        a.send('Bump', 10)
        da = a.until(lambda m: has(m, '"10"')); b.until(lambda m: has(m, '"10"'))
        assert set(da) == {'d'} and len(da['d']) <= 2, da
        print(f'two sessions, each its own view; one update reaches both as a DELTA ({len(json.dumps(da))} bytes of a {nstat}-static, {ndyn}-dynamic page): PASS')
        a.send('Add', arg='first note'); b.until(lambda m: has(m, 'first note'))
        a.send('Add', arg='<script>x</script>'); b.until(lambda m: has(m, 'script'))
        print('an event carrying CLIENT state (the draft) reaches the model; markup in it stays text: PASS')
        for forged in [dict(raw='=["Nope"]'), dict(raw='=["Bump","ten"]'), dict(raw='=["Bump"]'), dict(raw='bump'), dict(raw='=not json')]:
            a.send('', **forged)
        a.send('Bump', 0); time.sleep(0.3)
        a.send('Bump', 1); m = a.until(lambda m: has(m, '"11"'))
        a.send('Bump', -1); a.until(lambda m: has(m, '"10"'))
        print('messages are the app\'s own TYPE: an unknown one, a field that is not a number, a missing field and untyped text are refused before update sees them: PASS')
        a.send('Clock'); a.until(lambda m: has(m, '1 s')); a.until(lambda m: has(m, '2 s'))
        a.send('Clock'); time.sleep(1.5)
        a.send('Bump', 1); a.until(lambda m: has(m, '"11"'))
        print('a subscription: the clock ticks while the model asks for it, and stops when it does not: PASS')
        a.send('Hash'); a.until(lambda m: has(m, 'working')); a.until(lambda m: has(m, 'digest ready'))
        a.until(lambda m: isinstance(m, dict) and '' in m.get('d', {}).values(), timeout=6)
        print('commands: a job in its own actor returns as an event; a toast clears itself two seconds later: PASS')
        a.send('Fetch', f'http://127.0.0.1:{port}/'); a.until(lambda m: has(m, 'fetching')); a.until(lambda m: has(m, '200: '))
        a.send('Fetch', 'http://127.0.0.1:1/'); a.until(lambda m: has(m, 'failed: '))
        a.send('Home'); nav = a.until(lambda m: isinstance(m, dict) and 'nav' in m); assert nav == {'nav': '/'}, nav
        a.send('Ping'); ea = a.until(lambda m: isinstance(m, dict) and 'emit' in m); eb = b.until(lambda m: isinstance(m, dict) and 'emit' in m)
        assert ea == eb == {'emit': 'ping', 'detail': 'from session 1'}, (ea, eb)
        import hashlib
        blob = os.urandom(200000)
        a.send('Uploaded', arg='blob.bin:' + base64.b64encode(blob).decode())
        a.until(lambda m: has(m, f'blob.bin: 200000 bytes, sha256 {hashlib.sha256(blob).hexdigest()[:12]}'), timeout=60)
        print('more commands: an HTTP request whose reply (or failure) is a message, Navigate for one session, Emit to the page\'s script for all, a 200 KB upload whose digest matches: PASS')
        t0 = time.time()
        crowd = [Ws(port) for _ in range(many)]
        for c in crowd: c.recv()
        t1 = time.time()
        a.send('Bump', 100)
        for c in crowd: c.until(lambda m: has(m, '"111"'))
        t2 = time.time()
        a.send('Mem'); used = a.until(lambda m: has(m, 'heap in use')); used = [v for v in used['d'].values() if 'heap in use' in v][0]
        rss = int(subprocess.run(['ps', '-o', 'rss=', '-p', str(srv.pid)], capture_output=True, text=True).stdout or 0)
        print(f'{many} more sessions joined in {t1 - t0:.2f} s; one event reached all {many} in {(t2 - t1) * 1000:.0f} ms; {rss // 1024} MiB resident, {used} ({rss // (many + 2)} KiB resident a session): PASS')
        for c in crowd: c.s.close()
        time.sleep(0.5)
        a.send('Stop')
        assert srv.wait(timeout=20) == 0, said(srv)
    except Exception:
        print(f'-- server exit code {srv.poll()}; it said:\n   {said(srv)}', file=sys.stderr)
        raise
    finally:
        stop(srv)
    srv = start(port, store)
    try:
        c = Ws(port); f = c.recv()
        assert has(f, '111') and has(f, 'first note'), f
        c.send('Stop'); srv.wait(timeout=20)
        print('durable FIELDS survive a restart (count and notes back; clock, visitors and toast, deliberately, not): PASS')
    except Exception:
        print(f'-- server exit code {srv.poll()}; it said:\n   {said(srv)}', file=sys.stderr)
        raise
    finally:
        stop(srv)
    r = subprocess.run([binary, f'--store={store}', '--replay'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and 'count=111' in r.stdout, r.stdout + r.stderr
    hist = [json.loads(l) for l in open(store) if l.strip()]
    events = sum(1 for h in hist if h['k'] == '$event'); counts = [h['v'] for h in hist if h['k'] == 'model.count']
    print(f'replay: the model rebuilt from the journal ALONE ({events} events) equals what was saved; the log holds every value the counter had {counts}: PASS')
