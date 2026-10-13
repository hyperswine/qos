#!/usr/bin/env python3
"""Exercise the real Main Profile UI, onboard plugins, refusals and restart.

Opens a real GL window on macOS; uses DISPLAY or xvfb-run on Linux.
Retains screenshots and logs under --output (which must be a fresh directory).
"""
import argparse
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]


def png(path, rgb):
    def chunk(kind, data):
        return (struct.pack('!I', len(data)) + kind + data +
                struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff))
    raw = b''.join(b'\0' + rgb[i:i + 2880] for i in range(0, len(rgb), 2880))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
                     chunk(b'IHDR', struct.pack('!2I5B', 960, 600, 8, 2, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def check_live_deadline(out, env, profile):
    # Delay the real shell's render callback. The worker stays live beyond
    # its budget; Main must still drain storage and clear readiness.
    import re
    module = out / 'stalled-shell.fpr'
    text = (ROOT/'programs/mods/guishell.fpr').read_text()
    text = re.sub(r'use "(?!std/)([^"\n]+)"',
                  lambda m: 'use "' + str(ROOT/'programs/mods'/m[1]) + '"', text)
    text = text.replace('serviceBudgetMs = 5000.', 'serviceBudgetMs = 1000.')
    text = text.replace('staticView view done', 'staticView stalledView done')
    text += '\nstalledView self env vp model = _ = Sys.sleepUs 2000000; view self env vp model.\n'
    module.write_text(text)
    entry = out/'deadline-entry.fpr'
    entry.write_text('unsafe program.\nS = use "' + str(module.with_suffix('')) + '".\nmain = S.main.\n')
    p = subprocess.run(['make', '-s', 'qos-app', f'PROG={entry}',
                        f'QA_OUT={out/"deadline.qa"}', f'BUILD={out/"deadline-build"}'],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
    assert p.returncode == 0, p.stdout+p.stderr
    shutil.copyfile(profile/'Main.disk', out/'deadline.disk')
    p = subprocess.run([str(ROOT/'qos/qosp-gl'), '--yes', str(out/'deadline.qa')],
        cwd=out, env=dict(env, FPR_DISK=str(out/'deadline.disk'), FPR_EVDEV='/dev/null',
                         QOSP_READY_FILE=str(out/'deadline.ready')),
        capture_output=True, text=True, timeout=20)
    text = p.stdout+p.stderr
    (out/'deadline.log').write_text(text)
    assert p.returncode == 1 and 'deadline exceeded' in text and 'shell stopped: mvu:' in text, text
    assert text.index('storage drained and flushed') < text.index('shell stopped: mvu:'), text
    assert 'qosp: shutdown failed' in text and not (out/'deadline.ready').exists(), text
    assert 'deadlock --' not in text and 'SIGSEGV' not in text, text
    print('guishell: live render-worker deadline drains storage before failed exit HOLDS')


def check_pane_recovery(out, env, profile):
    # Change only the pane's namespace in a test-local copy. The real shell,
    # renderer and lifecycle services still run, without production fault hooks.
    import re
    tag = f'qos-pane-recovery-{os.getpid()}'
    module = out / 'pane-shell.fpr'
    text = (ROOT / 'programs/mods/guishell.fpr').read_text()
    text = re.sub(r'use "(?!std/)([^"\n]+)"',
                  lambda m: 'use "' + str(ROOT / 'programs/mods' / m[1]) + '"', text)
    text = text.replace('jobs = spawn (PJ.owner ns port serviceBudgetMs);',
                        'paneProvider = spawn fixtureNamespace;\n  jobs = spawn (PJ.owner paneProvider port serviceBudgetMs);')
    text = text.replace('_ = kill jobs;', '_ = kill jobs;\n  _ = kill paneProvider;')
    text += '''
fixtureNamespace me = fixtureLoop me False.
fixtureLoop me recovered =
  (from, id, EP.NsList prefix) = receive me;
  _ = AC.reply (from, id) (case recovered of
      True -> Ok "/recovered/\\n/data/\\n"
    | False -> Err "fixture service offline");
  fixtureLoop me True.
'''
    module.write_text(text)
    entry = out / 'pane-entry.fpr'
    entry.write_text('unsafe program.\nS = use "' + str(module.with_suffix('')) +
                     '".\nmain = S.run "' + tag + '".\n')
    built = subprocess.run(['make', '-s', 'qos-app', f'PROG={entry}',
                            f'QA_OUT={out / "pane-recovery.qa"}', f'BUILD={out / "pane-recovery-build"}'],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
    (out / 'pane-recovery-build.log').write_text(built.stdout + built.stderr)
    assert built.returncode == 0, built.stdout + built.stderr
    shutil.copyfile(profile / 'Main.disk', out / 'pane-recovery.disk')
    fifo, ready = out / 'pane-keys.evd', out / 'pane.ready'
    os.mkfifo(fifo)
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    proc = subprocess.Popen([str(ROOT / 'qos/qosp-gl'), '--yes', str(out / 'pane-recovery.qa')],
                            cwd=out, env=dict(env, FPR_DISK=str(out / 'pane-recovery.disk'),
                                              FPR_EVDEV=str(fifo), QOSP_READY_FILE=str(ready)),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    messages, log = queue.Queue(), []

    def reader():
        for line in proc.stdout:
            messages.put(line)
        messages.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def wait_for(expected):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            line = messages.get(timeout=max(.1, deadline - time.monotonic()))
            assert line is not None, ''.join(log)
            log.append(line)
            assert 'PANIC' not in line and 'SIGSEGV' not in line, line
            if expected in line:
                return
        raise TimeoutError(expected)

    def key(code):
        for value in (1, 0):
            os.write(fd, struct.pack('llHHi', 0, 0, 1, code, value))
        time.sleep(.25)

    def snapshot(n):
        path = Path(f'/tmp/{tag}-{n}.ppm')
        assert not path.exists(), path
        key(25)
        wait_for(f'shell: snapshot {n}')
        deadline = time.monotonic() + 10
        while not path.exists() or path.stat().st_size < 960 * 600 * 3:
            if time.monotonic() >= deadline:
                raise TimeoutError(path)
            time.sleep(.05)
        data = path.read_bytes()
        rgb = data.split(b'\n', 3)[3]
        png(out / f'pane-recovery-{n}.png', rgb)
        shutil.move(path, out / f'pane-recovery-{n}.ppm')
        return rgb

    try:
        wait_for('Main Profile ready')
        key(106); key(28)
        wait_for('shell: pane 1 Unavailable: fixture service offline')
        refused = snapshot(1)
        key(19)
        wait_for('shell: pane 1 R Refresh')
        recovered = snapshot(2)
        assert refused != recovered, 'retry did not change the rendered pane'
        assert proc.poll() is None and ready.read_text().strip() == str(proc.pid)
        key(1); wait_for('shell: home')
        key(16)
        proc.wait(timeout=10)
        thread.join(timeout=5)
        assert not thread.is_alive()
        while not messages.empty():
            line = messages.get_nowait()
            if line is not None:
                log.append(line)
        text = ''.join(log)
        assert proc.returncode == 0 and 'storage drained and flushed' in text, text
        assert not ready.exists()
        print('guishell: visible pane failure, explicit retry, Home and clean shutdown HOLDS')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait(timeout=5)
        thread.join(timeout=5)
        proc.stdout.close()
        os.close(fd)
        fifo.unlink(missing_ok=True)
        (out / 'pane-recovery.log').write_text(''.join(log))
        for n in (1, 2, 3):
            path = Path(f'/tmp/{tag}-{n}.ppm')
            if path.exists():
                shutil.move(path, out / f'pane-recovery-{n}.ppm')


def check(out):
    out.mkdir(parents=True, exist_ok=False)
    tag = f'qos-shell-check-{os.getpid()}'
    # Exercise the normal multi-worker scheduler: a single hart hides GL
    # ownership bugs when a graphics actor wakes on a different worker.
    env = dict(os.environ, XDG_CACHE_HOME=str(out / 'cache'),
               FPR_HARTS=os.environ.get('FPR_HARTS', '4'), FPR_PORT='0')

    def run(*args):
        p = subprocess.run(list(map(str, args)), cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=240)
        with (out / 'build.log').open('a') as f:
            f.write(p.stdout + p.stderr)
        assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]

    profile = out / 'profile'
    run('python3', 'tools/main-profile.py', '--output', profile)
    # Isolate test snapshots from a concurrently running interactive shell.
    entry = out / 'shell-check.fpr'
    entry.write_text('unsafe program.\nS = use "' +
                     str(ROOT / 'programs/mods/guishell') +
                     '".\nmain = S.run "' + tag + '".\n')
    run('make', '-s', 'qos-app', f'PROG={entry}',
        f'QA_OUT={out / "check.qa"}', f'BUILD={out / "check-build"}')
    # Exercise the actual appliance session script with a runner that records
    # its selected disk. This checks boot wiring, not a Linux image boot.
    recorder = out / 'session-runner'
    recorder.write_text('#!/bin/sh\nprintf "%s\\n" "$FPR_DISK"\n')
    recorder.chmod(0o755)
    state = out / 'session-state'
    session_env = dict(env, QOSP_BIN=str(recorder), QOSP_SHARE=str(profile),
                       QOSP_APP=str(profile / 'main.qa'), QOSP_STATE=str(state),
                       QOSP_NO_WAIT_DRI='1')
    session_env.pop('FPR_DISK', None)
    session = ROOT / 'tools/buildroot/package/qosp/qosp-session'
    def start_session():
        return subprocess.check_output(['sh', str(session)], env=session_env, text=True).strip()
    assert start_session() == str(state / 'Main.disk')
    assert (state / 'Main.disk').read_bytes() == (profile / 'Main.disk').read_bytes()
    (state / 'Main.disk').write_bytes(b'existing writable state')
    assert start_session() == str(state / 'Main.disk')
    assert (state / 'Main.disk').read_bytes() == b'existing writable state'
    session_env['FPR_DISK'] = str(out / 'explicit.disk')
    assert start_session() == str(out / 'explicit.disk')
    run('make', '-s', 'plugin-qa', 'PROG=tests/plugmini.fpr',
        f'PLUG_OUT={profile / "plugmini.qa"}', f'BUILD={out / "mini-build"}')
    (profile / 'broken.qa').write_bytes(b'not a QA archive')
    disk = out / 'check.disk'
    run('python3', 'tools/mkdisk.py', disk, 32,
        *[profile / (name + '.qa') for name in ['clock', 'logs', 'browser', 'disk', 'plugmini', 'broken']])
    run('make', '-s', 'qos-app', 'PROG=tests/guishell.fpr',
        f'QA_OUT={out / "unit.qa"}', f'BUILD={out / "unit-build"}')
    run('make', '-s', 'qos-app', 'PROG=tests/scrolltext.fpr',
        f'QA_OUT={out / "scrolltext.qa"}', f'BUILD={out / "scrolltext-build"}')
    run('make', '-s', 'qos-app', 'PROG=tests/panemvu.fpr',
        f'QA_OUT={out / "panemvu.qa"}', f'BUILD={out / "panemvu-build"}')
    run('make', '-s', '-C', 'qos', 'portable-gl')
    unit = subprocess.run([str(ROOT / 'qos/qosp-gl'), '--yes', str(out / 'unit.qa')],
                          cwd=out, env=env, capture_output=True, text=True, timeout=30)
    (out / 'unit.log').write_text(unit.stdout + unit.stderr)
    assert unit.returncode == 0 and 'guishell: HOLDS' in unit.stdout, unit.stdout + unit.stderr
    assert 'PANIC' not in unit.stdout + unit.stderr
    scroll = subprocess.run([str(ROOT / 'qos/qosp-gl'), '--yes', str(out / 'scrolltext.qa')],
                            cwd=out, env=env, capture_output=True, text=True, timeout=30)
    (out / 'scrolltext.log').write_text(scroll.stdout + scroll.stderr)
    assert scroll.returncode == 0 and 'scrolltext: HOLDS' in scroll.stdout, scroll.stdout + scroll.stderr
    pane = subprocess.run([str(ROOT / 'qos/qosp-gl'), '--yes', str(out / 'panemvu.qa')],
                          cwd=out, env=env, capture_output=True, text=True, timeout=30)
    (out / 'panemvu.log').write_text(pane.stdout + pane.stderr)
    assert pane.returncode == 0 and 'panemvu: HOLDS' in pane.stdout, pane.stdout + pane.stderr
    env['FPR_DISK'] = str(disk)
    command = [str(ROOT / 'qos/qosp-gl'), '--yes', str(out / 'check.qa')]

    for boot in (1, 2):
        fifo = out / f'keys-{boot}.evd'
        os.mkfifo(fifo)
        fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        env['FPR_EVDEV'] = str(fifo)
        ready = out / f'ready-{boot}'
        ready.write_text('424242\n')
        env['QOSP_READY_FILE'] = str(ready)
        proc = subprocess.Popen(command, cwd=out, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        lines = queue.Queue()
        log = []

        def reader():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()

        def wait_for(text):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                line = lines.get(timeout=max(.1, deadline - time.monotonic()))
                assert line is not None, ''.join(log)
                log.append(line)
                assert 'PANIC' not in line and 'SIGSEGV' not in line, line
                if text in line:
                    return
            raise TimeoutError(text)

        def key(code):
            for value in (1, 0):
                os.write(fd, struct.pack('llHHi', 0, 0, 1, code, value))
            time.sleep(.25)

        def shot(n):
            path = Path(f'/tmp/{tag}-{n}.ppm')
            assert not path.exists(), f'old capture: {path}'
            key(25)
            wait_for(f'shell: snapshot {n}')
            await_capture(path)
            data = path.read_bytes()
            assert data.startswith(b'P6\n960 600\n255\n'), data[:60]
            rgb = data.split(b'\n', 3)[3]
            assert len(rgb) == 960 * 600 * 3 and len(set(rgb[::97])) > 5
            assert sum(r > 160 and g > 160 and b > 160
                       for r, g, b in zip(rgb[::3], rgb[1::3], rgb[2::3])) > 100, 'labels missing'
            shutil.move(path, out / f'boot{boot}-{n}.ppm')
            png(out / f'boot{boot}-{n}.png', rgb)
            return rgb

        def await_capture(path):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if path.exists() and path.stat().st_size >= 960 * 600 * 3:
                    return
                time.sleep(.05)
            raise TimeoutError(f'capture not written: {path}')

        try:
            wait_for('Main Profile ready (10 shortcuts, 2 pages)')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (not ready.exists() or ready.read_text().strip() != str(proc.pid)):
                time.sleep(.01)
            assert ready.exists() and ready.read_text().strip() == str(proc.pid), 'Main did not publish current-PID readiness'
            first = shot(1)
            key(109); wait_for('shell: page 2')
            second = shot(2)
            assert first != second
            key(28); wait_for('shell: open browser')
            browser = shot(3)
            assert browser != second
            key(108); key(28)
            resolved = shot(4)
            assert browser != resolved, 'onboard browser update did not change its view'
            key(1); wait_for('shell: home'); await_capture(Path(f'/tmp/{tag}-5.ppm'))
            shutil.move(f'/tmp/{tag}-5.ppm', out / f'boot{boot}-5.ppm')
            key(106); key(106); key(28); wait_for('shell: open plugmini')
            refusal = shot(6)
            key(106); key(28); wait_for('shell: open broken')
            broken = shot(7)
            assert refusal != broken, 'distinct launch refusals were not displayed'
            key(104); wait_for('shell: page 1')
            key(108); key(106); key(28); wait_for('shell: open clock')
            clock = shot(8)
            assert clock != first, 'loaded clock did not draw'
            key(1); wait_for('shell: home'); await_capture(Path(f'/tmp/{tag}-9.ppm'))
            shutil.move(f'/tmp/{tag}-9.ppm', out / f'boot{boot}-9.ppm')
            key(105); key(105); key(105); key(28); wait_for('shell: open files'); wait_for('shell: pane 1 R Refresh')
            files = shot(10)
            # Each namespace entry occupies its own row in the fixed viewport.
            # Count bright text in separate row bands, excluding the scrollbar.
            def row_ink(rgb, y):
                return sum(all(v > 160 for v in rgb[(yy * 960 + x) * 3:(yy * 960 + x) * 3 + 3])
                           for yy in range(y, y + 24) for x in range(65, 870))
            assert sum(row_ink(files, 236 + row * 26) > 20 for row in range(9)) >= 6, 'Files is not a vertical list'
            key(109)
            files_bottom = shot(11)
            assert files_bottom != files, 'Files page-down did not scroll'
            key(102)
            assert shot(12) == files, 'Files Home did not return to the first row'
            key(1); wait_for('shell: home'); await_capture(Path(f'/tmp/{tag}-13.ppm'))
            shutil.move(f'/tmp/{tag}-13.ppm', out / f'boot{boot}-13.ppm')
            key(106); key(28); wait_for('shell: open logs'); wait_for('shell: pane 2 R Refresh')
            logs = shot(14)
            assert sum(row_ink(logs, 236 + row * 26) > 20 for row in range(9)) >= 6, 'Logs is not a vertical list'
            key(107)
            assert shot(15) != logs, 'Logs End did not scroll'
            key(1); wait_for('shell: home'); await_capture(Path(f'/tmp/{tag}-16.ppm'))
            shutil.move(f'/tmp/{tag}-16.ppm', out / f'boot{boot}-16.ppm')
            if boot == 1:
                key(16)
            else:
                proc.terminate()
            proc.wait(timeout=10)
            reader_thread.join(timeout=5)
            assert not reader_thread.is_alive(), 'Main output did not reach EOF'
            while not lines.empty():
                line = lines.get_nowait()
                if line is not None:
                    log.append(line)
            text = ''.join(log)
            assert proc.returncode == 0, text
            assert ('shell ended' if boot == 1 else 'qosp: shutdown complete') in text, text
            if boot == 1:
                assert 'shell: storage drained and flushed' in text, text
            # Signal completion is acknowledged by the host only after the
            # lifecycle barrier. Sys.logAt's console echo is rate limited.
            assert not ready.exists(), 'Main left a stale readiness marker'
            assert '[desktopgl] GLFW' in ''.join(log), 'no real GL initialization'
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=5)
            proc.stdout.close()
            os.close(fd)
            fifo.unlink(missing_ok=True)
            (out / f'boot{boot}.log').write_text(''.join(log))
            for n in range(1, 17):
                p = Path(f'/tmp/{tag}-{n}.ppm')
                if p.exists():
                    shutil.move(p, out / f'boot{boot}-{n}.ppm')
    # A dependency death must reach Main's lifecycle barrier before the
    # primary failure is reported. Use only this test's graphics owner/disk.
    failure = out / 'failure.fpr'
    failure.write_text('unsafe program.\n' +
        'S = use "' + str(ROOT/'programs/mods/guishell') + '".\n' +
        'QS = use "' + str(ROOT/'programs/mods/qsys') + '".\n' +
        'GX = use "' + str(ROOT/'programs/mods/graphics') + '".\n' +
        'MV = use "std/mvu".\n' +
        'fault me env event model = case event of\n' +
        '    MV.ETick -> (q, tiles, mt, jobs) = env; QS.Qsys ns st vfs log apps = q;\n' +
        '      ep = case GX.attach me ns "failure" of Ok value -> value | Err why -> error why;\n' +
        '      (graphics, handle) = ep; _ = kill graphics; (model, Nil)\n' +
        '  | other -> S.update me env event model.\n' +
        'main = S.runWith "qos-shell-failure" fault.\n')
    run('make', '-s', 'qos-app', f'PROG={failure}',
        f'QA_OUT={out/"failure.qa"}', f'BUILD={out/"failure-build"}')
    shutil.copyfile(profile/'Main.disk', out/'failure.disk')
    fault_env = dict(env, FPR_DISK=str(out/'failure.disk'), FPR_EVDEV='/dev/null',
                     QOSP_READY_FILE=str(out/'failure.ready'))
    failed = subprocess.run([str(ROOT/'qos/qosp-gl'), '--yes', str(out/'failure.qa')],
                            cwd=out, env=fault_env, capture_output=True, text=True, timeout=20)
    text = failed.stdout + failed.stderr
    (out/'failure.log').write_text(text)
    assert failed.returncode == 1 and 'shell stopped: mvu:' in text, text
    assert 'storage drained and flushed' in text and 'qosp: shutdown failed' in text, text
    assert text.index('storage drained and flushed') < text.index('shell stopped: mvu:'), text
    assert 'deadlock --' not in text and 'SIGSEGV' not in text, text
    assert not (out/'failure.ready').exists(), text
    print('guishell: graphics death drains storage before failed exit HOLDS')
    check_live_deadline(out, env, profile)
    check_pane_recovery(out, env, profile)
    print('guishell: real GL, Files/Logs vertical scrolling, two pages, onboard clock/browser, refusals, pointer protocol and two boots HOLDS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' and not os.environ.get('DISPLAY'):
        xvfb = shutil.which('xvfb-run')
        assert xvfb, 'needs DISPLAY or xvfb-run'
        # Wrap the harness, so Popen owns qosp directly. Wrapping only the
        # child compares readiness to the shell wrapper's PID and leaves
        # qosp holding stdout open when that wrapper is terminated.
        os.execv(xvfb, [xvfb, '-a', sys.executable, str(Path(__file__).resolve()),
                       *sys.argv[1:]])
    check(args.output.resolve())
