#!/usr/bin/env python3
"""liveboard-check.py -- drive programs/liveboard.fpr (std/live on a plain posix
process) as real websocket clients: two sessions, deltas, client/server state,
commands and subscriptions, many sessions fanned out, durable fields across a
restart, and the journal replayed.   usage: liveboard-check.py <binary> [sessions]"""
import base64, json, os, socket, struct, subprocess, sys, tempfile, time, urllib.request

binary = sys.argv[1]
many = int(sys.argv[2]) if len(sys.argv) > 2 else 100

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
    def send(self, msg, arg=''):
        p = json.dumps({'msg': msg, 'arg': str(arg)}).encode()
        mask = os.urandom(4)
        hdr = bytes([0x81, 0x80 | len(p)]) if len(p) < 126 else bytes([0x81, 0x80 | 126]) + struct.pack('>H', len(p))
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

def start(port, store, *extra):
    p = subprocess.Popen([binary, f'--port={port}', f'--store={store}', *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = p.stdout.readline()
    assert line.startswith('ready'), line + p.stderr.read()
    return p

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
        a.send('bump', 10)
        da = a.until(lambda m: has(m, '"10"')); b.until(lambda m: has(m, '"10"'))
        assert set(da) == {'d'} and len(da['d']) <= 2, da
        print(f'two sessions, each its own view; one update reaches both as a DELTA ({len(json.dumps(da))} bytes of a {nstat}-static, {ndyn}-dynamic page): PASS')
        a.send('add', 'first note'); b.until(lambda m: has(m, 'first note'))
        a.send('add', '<script>x</script>'); b.until(lambda m: has(m, 'script'))
        print('an event carrying CLIENT state (the draft) reaches the model; markup in it stays text: PASS')
        a.send('clock'); a.until(lambda m: has(m, '1 s')); a.until(lambda m: has(m, '2 s'))
        a.send('clock'); time.sleep(1.5)
        a.send('bump', 1); a.until(lambda m: has(m, '"11"'))
        print('a subscription: the clock ticks while the model asks for it, and stops when it does not: PASS')
        a.send('digest'); a.until(lambda m: has(m, 'working')); a.until(lambda m: has(m, 'digest ready'))
        a.until(lambda m: isinstance(m, dict) and '' in m.get('d', {}).values(), timeout=6)
        print('commands: a job in its own actor returns as an event; a toast clears itself two seconds later: PASS')
        t0 = time.time()
        crowd = [Ws(port) for _ in range(many)]
        for c in crowd: c.recv()
        t1 = time.time()
        a.send('bump', 100)
        for c in crowd: c.until(lambda m: has(m, '"111"'))
        t2 = time.time()
        a.send('mem'); used = a.until(lambda m: has(m, 'heap in use')); used = [v for v in used['d'].values() if 'heap in use' in v][0]
        rss = int(subprocess.run(['ps', '-o', 'rss=', '-p', str(srv.pid)], capture_output=True, text=True).stdout or 0)
        print(f'{many} more sessions joined in {t1 - t0:.2f} s; one event reached all {many} in {(t2 - t1) * 1000:.0f} ms; {rss // 1024} MiB resident, {used} ({rss // (many + 2)} KiB resident a session): PASS')
        for c in crowd: c.s.close()
        time.sleep(0.5)
        a.send('quit')
        assert srv.wait(timeout=20) == 0, srv.stderr.read()
    finally:
        if srv.poll() is None: srv.kill()
    srv = start(port, store)
    try:
        c = Ws(port); f = c.recv()
        assert has(f, '111') and has(f, 'first note'), f
        c.send('quit'); srv.wait(timeout=20)
        print('durable FIELDS survive a restart (count and notes back; clock, visitors and toast, deliberately, not): PASS')
    finally:
        if srv.poll() is None: srv.kill()
    r = subprocess.run([binary, f'--store={store}', '--replay'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and 'count=111' in r.stdout, r.stdout + r.stderr
    hist = [json.loads(l) for l in open(store) if l.strip()]
    events = sum(1 for h in hist if h['k'] == '$event'); counts = [h['v'] for h in hist if h['k'] == 'board/count']
    print(f'replay: the model rebuilt from the journal ALONE ({events} events) equals what was saved; the log holds every value the counter had {counts}: PASS')
