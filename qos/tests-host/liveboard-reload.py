#!/usr/bin/env python3
"""liveboard-reload.py -- std/live reload on posix: a broken edit keeps the old
program serving; a good edit is rebuilt, the server BECOMES the new program, and
durable state is still there.  Run from the qos root.  usage: liveboard-reload.py <binary>"""
import subprocess, sys, time, os, tempfile, shutil, json
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'liveboard-check.py')).read().split("with tempfile.TemporaryDirectory() as t:")[0]
exec(src.replace("binary = sys.argv[1]", "binary = sys.argv[1]").replace("many = int(sys.argv[2]) if len(sys.argv) > 2 else 100", "many = 0"))
t = tempfile.mkdtemp(); port = free_port(); store = f'{t}/b.kvlog'
app = 'programs/liveboard.fpr'; backup = open(app).read()
err = open(f'{t}/err', 'w')
srv = subprocess.Popen([sys.argv[1], f'--port={port}', f'--store={store}', '--dev'], stdout=subprocess.PIPE, stderr=err, text=True)
try:
    assert srv.stdout.readline().startswith('ready')
    a = Ws(port); f = a.recv(); assert 'Live board' in ''.join(f['s'])
    a.send('Bump', 7); a.until(lambda m: has(m, '"7"'))
    # 1. a change that does NOT compile: the old program must keep serving
    open(app, 'w').write(backup.replace('Ma.display "Live board"', 'Ma.display ("Live board"'))
    time.sleep(4); a.send('Bump', 1); a.until(lambda m: has(m, '"8"'))
    print('a rebuild that FAILS is reported and the old program keeps serving: PASS')
    # 2. a real edit: new heading
    open(app, 'w').write(backup.replace('Ma.display "Live board"', 'Ma.display "Live board, reloaded"'))
    t0 = time.time()
    while True:
        try:
            b = Ws(port, timeout=3); f = b.recv(timeout=3)  # short: a client caught mid-restart must not wait a minute
            if 'reloaded' in ''.join(f['s']): break
            b.s.close()
        except Exception as e: sys.stderr.write(f'  [{time.time() - t0:.1f}s] {e!r}\n')
        if time.time() - t0 > 40:
            diag = ''
            try: diag = urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=5).read().decode()[-300:]
            except Exception as e: diag = 'GET / failed: ' + repr(e)
            try:
                w = Ws(port); fr = w.recv(timeout=5); diag += '\nWS first frame statics: ' + ''.join(fr.get('s', []))[:400]
            except Exception as e: diag += '\nWS failed: ' + repr(e)
            raise AssertionError('no reload in 40 s\n' + diag + '\n' + subprocess.run('pgrep -fl liveboard', shell=True, capture_output=True, text=True).stdout + open(f'{t}/err').read()[-600:])
        time.sleep(0.3)
    assert has(f, '"8"'), f
    print(f'an edit to the source: rebuilt, restarted into the new program in {time.time() - t0:.1f} s, the new view is served and the counter is still 8: PASS')
    b.send('Stop')
finally:
    open(app, 'w').write(backup)
    time.sleep(1); subprocess.run(['pkill', '-f', f'liveboard-{port}.bin']); 
    if srv.poll() is None: srv.kill()
print(''.join(l for l in open(f'{t}/err') if l.startswith('live:'))[-700:])
