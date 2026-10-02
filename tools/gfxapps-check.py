#!/usr/bin/env python3
"""Real shared GL: Terra II + dungeon, focused keys, close/restart and pixels.
On macOS this opens a GLFW window. On Linux it uses xvfb-run when DISPLAY
is unset. Output artifacts can be retained with --output DIRECTORY.
"""
from pathlib import Path
import argparse
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def run(args, env, timeout=240):
    p = subprocess.run(list(map(str, args)), cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise AssertionError(f'{args}: exit {p.returncode}\n{p.stdout[-5000:]}{p.stderr[-5000:]}')
    return p


def pixels(path):
    with path.open('rb') as f:
        assert f.readline() == b'P6\n', path
        assert f.readline() == b'960 600\n', path
        assert f.readline() == b'255\n', path
        data = f.read()
    assert len(data) == 960 * 600 * 3, path
    assert len(set(data[::97])) > 30, f'blank or uniform frame: {path}'
    return data


def check(out):
    env = dict(os.environ, XDG_CACHE_HOME=str(out / 'cache'), FPR_HARTS='1',
               FPR_DISK=str(out / 'disk'), FPR_SND_MUSIC='0',
               FPR_ASSETS=str(ROOT / 'models/music'))
    archive = out / 'gfxapps.qa'
    run(['make', '-s', 'qos-app', 'PROG=tests/gfxapps.fpr', f'QA_OUT={archive}', f'BUILD={out / "app-build"}'], env)
    run(['make', '-s', '-C', 'qos', 'portable-gl'], env)
    # Graphics writes these unique test names. Refuse to overwrite an old artifact.
    names = ['gfxapps-terra-1', 'gfxapps-terra-2', 'gfxapps-dungeon-1', 'gfxapps-dungeon-2', 'gfxapps-restart-1']
    paths = [Path('/tmp') / (name + '.ppm') for name in names]
    for path in paths:
        if path.exists():
            raise AssertionError(f'old snapshot exists: {path}; move it before rerunning')
    command = [str(ROOT / 'qos/qosp-gl'), '--yes', str(archive)]
    if sys.platform != 'darwin' and not env.get('DISPLAY'):
        if not shutil.which('xvfb-run'):
            raise RuntimeError('needs DISPLAY or xvfb-run for the real GL backend')
        command = ['xvfb-run', '-a', *command]
    fifo = out / "keys.evd"
    os.mkfifo(fifo)
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    env["FPR_EVDEV"] = str(fifo)
    try:
        proc = subprocess.Popen(command, cwd=out, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    except BaseException:
        os.close(fd)
        fifo.unlink(missing_ok=True)
        raise
    lines = queue.Queue()
    def reader():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)
    threading.Thread(target=reader, daemon=True).start()
    def key(code):
        # Linux input_event layout, also used by the Portable replay driver on macOS.
        os.write(fd, struct.pack('llHHi', 0, 0, 1, code, 1))
        os.write(fd, struct.pack('llHHi', 0, 0, 1, code, 0))
    log = []
    sent = set()
    deadline = time.monotonic() + 60
    try:
        while True:
            line = lines.get(timeout=max(.1, deadline - time.monotonic()))
            if line is None:
                break
            log.append(line)
            if 'gfxapps: inject terra' in line and 'terra' not in sent:
                key(28); time.sleep(1); key(25)
                sent.add('terra')
            if 'gfxapps: inject dungeon' in line and 'dungeon' not in sent:
                key(57); time.sleep(1); key(25)
                sent.add('dungeon')
            if time.monotonic() >= deadline:
                raise TimeoutError('shared graphics run exceeded 60 seconds')
        proc.wait(timeout=5)
        text = ''.join(log)
        (out / 'run.log').write_text(text)
        assert proc.returncode == 0 and 'gfxapps: HOLDS' in text, text
        assert 'PANIC' not in text and 'SIGSEGV' not in text, text
        assert sent == {'terra', 'dungeon'}, text
        assert text.count('[desktopgl] GLFW') >= 1, 'the real GL backend did not initialize'
        assert 'all sessions closed' in text and 'terra restarted; dungeon still running' in text
        frames = []
        for path in paths:
            frames.append(pixels(path))
            shutil.move(path, out / path.name)
        assert frames[0] != frames[1], 'Terra focused keys did not change its frame'
        assert frames[2] != frames[3], 'Dungeon focused keys did not change its frame'
        assert frames[1] != frames[3], 'the two games drew the same pixels'
        print('gfxapps: real GL, two real games, focused input, close/restart and five captures HOLDS')
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
        (out / 'run.log').write_text(''.join(log))
        # Move partial snapshots too, so a failed run is inspectable and repeatable.
        for path in paths:
            if path.exists():
                shutil.move(path, out / path.name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        check(args.output.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='qos-gfxapps-') as tmp:
            check(Path(tmp))
