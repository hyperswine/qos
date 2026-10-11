#!/usr/bin/env python3
"""Real host signals reach FP-RISC drain/flush, or a bounded failed exit.

Readiness is an explicit app claim, atomically carrying the current host PID.
The positive leg persists through Files and replays in a fresh host process;
the refusal legs distinguish failed completion from an unacknowledged timeout.
"""
from pathlib import Path
import array
import fcntl
import os
import pty
import shutil
import signal
import subprocess
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd=ROOT, timeout=240):
    p = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True,
                       text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.stdout}{p.stderr}'
    return p.stdout + p.stderr


def build(source, out, work):
    run(['make', '-s', 'qos-app', f'PROG={source}', f'QA_OUT={out}', f'BUILD={work}'])


def start(host, app, directory, harts, timeout_ms=5000, tty=False, extra=None):
    ready = directory / 'ready'
    ready.write_text('424242\n') # must never satisfy readiness for this child
    output = (directory / f'run-{time.monotonic_ns()}.log').open('w+')
    env = {**os.environ, 'FPR_HARTS': str(harts), 'FPR_DISK': str(directory / 'disk'),
           'FPR_PORT': '0', 'QOSP_READY_FILE': str(ready),
           'QOSP_SHUTDOWN_MS': str(timeout_ms), **(extra or {})}
    master, slave = pty.openpty() if tty else (None, None)
    p = subprocess.Popen([str(host), '--yes', str(app)], cwd=directory, env=env,
                         stdin=slave if tty else subprocess.DEVNULL,
                         stdout=output, stderr=subprocess.STDOUT)
    if slave is not None:
        os.close(slave)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if ready.exists() and ready.read_text().strip() == str(p.pid):
            return p, ready, output, master
        if p.poll() is not None:
            output.seek(0)
            raise AssertionError(f'app exited before readiness: {p.returncode}\n{output.read()}')
        time.sleep(.01)
    p.kill()
    p.wait()
    output.seek(0)
    raise AssertionError(f'no current-PID readiness\n{output.read()}')


def stop(handle, sig=signal.SIGTERM, repeat=False):
    p, ready, output, master = handle
    began = time.monotonic()
    p.send_signal(sig)
    if repeat:
        try:
            p.send_signal(sig)
        except ProcessLookupError:
            pass
    try:
        status = p.wait(timeout=8)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        raise AssertionError('host exceeded shutdown deadline')
    elapsed = time.monotonic() - began
    output.seek(0)
    text = output.read()
    output.close()
    if master is not None:
        os.close(master)
    if status != 124:
        assert not ready.exists(), f'exited host left readiness marker: {text}'
    return status, elapsed, text


with tempfile.TemporaryDirectory(prefix='qos-portable-shutdown-') as d:
    tmp = Path(d)
    host, app = tmp / 'qosp', tmp / 'shutdown.qa'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}',
         'FPRBUILD_EXTRA=--cflag -DQOS_BLK_TEST --cflag -DQOS_STORE_TEST'], cwd=ROOT / 'qos')
    build(ROOT / 'tests/portableshutdown.fpr', app, tmp / 'app')
    for harts in (1, 2):
        work = tmp / f'persist-{harts}'
        work.mkdir()
        for second in (False, True):
            result = stop(start(host, app, work, harts, tty=second),
                          signal.SIGINT if second else signal.SIGTERM, repeat=True)
            status, elapsed, text = result
            assert status == 0 and elapsed < 5, result
            assert 'storage drained and flushed' in text and 'qosp: shutdown complete' in text, text
            assert 'shutdown deadline expired' not in text, text
            if second:
                assert 'portableshutdown: replayed=committed' in text, text
        print(f'Portable shutdown: {harts} hart(s), SIGTERM/SIGINT, TTY, repeated request, fresh-PID readiness and durable replay HOLDS', flush=True)

    # On a committed image: open probes the device once, the append has two
    # barriers, and the fourth is Lifecycle's final post-drain flush.
    for name, fault, want, timeout_ms in (
        ('flush-error', {'QOS_BLK_TEST_FAIL_FLUSH_AT': '4'}, 1, 5000),
        ('flush-stall', {'QOS_BLK_TEST_FLUSH_DELAY_AT': '4',
                         'QOS_BLK_TEST_FLUSH_DELAY_US': '2000000'}, 124, 250),
    ):
        work = tmp / name
        work.mkdir()
        shutil.copyfile(tmp / 'persist-2/disk', work / 'disk')
        status, elapsed, text = stop(start(host, app, work, 2, timeout_ms=timeout_ms, extra=fault))
        assert status == want and elapsed < 1.5, (status, elapsed, text)
        assert 'qosp: shutdown complete' not in text, text
        if want == 1:
            assert 'storage: shutdown failed' in text and 'qosp: shutdown failed' in text, text
        print(f'Portable shutdown: actual {name} reports exit {want} without a clean claim HOLDS', flush=True)

    # Ordinary application completion uses the same FP-RISC coordinator.
    normal = tmp / 'normal.fpr'
    source = (ROOT / 'tests/portableshutdown.fpr').read_text()
    source = source.replace('use "std/', f'use "{ROOT}/std/')
    source = source.replace('  wait ctx.',
                            '  case Lifecycle.stop me ctx of Ok value -> print "normal: {value}" | Err why -> error why.')
    normal.write_text(source)
    build(normal, tmp / 'normal.qa', tmp / 'normal-app')
    normal_dir = tmp / 'normal'
    normal_dir.mkdir()
    p = subprocess.run([str(host), '--yes', str(tmp / 'normal.qa')], cwd=normal_dir,
                       env={**os.environ, 'FPR_HARTS': '2', 'FPR_PORT': '0',
                            'FPR_DISK': str(normal_dir / 'disk'),
                            'QOSP_READY_FILE': str(normal_dir / 'ready')},
                       capture_output=True, text=True, timeout=15)
    assert p.returncode == 0 and 'normal: storage drained and flushed' in p.stdout + p.stderr, p
    assert '[qos] normal => ()' in p.stdout + p.stderr, p
    assert not (normal_dir / 'ready').exists()
    print('Portable shutdown: ordinary app return drains and flushes HOLDS', flush=True)

    work = tmp / 'normal-stalled-flush'
    work.mkdir()
    shutil.copyfile(tmp / 'persist-2/disk', work / 'disk')
    began = time.monotonic()
    p = subprocess.run([str(host), '--yes', str(tmp / 'normal.qa')], cwd=work,
                       env={**os.environ, 'FPR_HARTS': '2', 'FPR_PORT': '0',
                            'FPR_DISK': str(work / 'disk'),
                            'QOSP_READY_FILE': str(work / 'ready'), 'QOSP_SHUTDOWN_MS': '250',
                            'QOS_BLK_TEST_FLUSH_DELAY_AT': '4',
                            'QOS_BLK_TEST_FLUSH_DELAY_US': '2000000'},
                       capture_output=True, text=True, timeout=2)
    elapsed = time.monotonic() - began
    assert p.returncode == 124 and elapsed < 1.5, (p, elapsed)
    assert 'normal: storage drained and flushed' not in p.stdout + p.stderr, p
    print('Portable shutdown: normal stop with stalled flush has a bounded failed exit HOLDS', flush=True)

    # Panic persistence is synchronous host KV I/O. It must arm its own
    # deadline before entering a storage barrier, without an OS signal.
    panic = tmp / 'panic.fpr'
    panic.write_text('unsafe program.\nmain = error "panic persistence deadline probe".\n')
    image = tmp / 'panic.qa'
    build(panic, image, tmp / 'panic-app')
    work = tmp / 'panic-stalled-sync'
    work.mkdir()
    began = time.monotonic()
    p = subprocess.run([str(host), '--yes', str(image)], cwd=work,
                       env={**os.environ, 'FPR_HARTS': '2', 'FPR_PORT': '0',
                            'QOSP_SHUTDOWN_MS': '250',
                            'QOS_STORE_TEST_SYNC_DELAY_US': '2000000'},
                       capture_output=True, text=True, timeout=2)
    elapsed = time.monotonic() - began
    assert p.returncode == 124 and elapsed < 1.5, (p, elapsed)
    assert 'qosp: shutdown complete' not in p.stdout + p.stderr, p
    print('Portable shutdown: panic persistence with stalled KV sync has a bounded failed exit without an OS signal HOLDS', flush=True)

    for code in (0, 1):
        source = tmp / f'software-complete-{code}.fpr'
        source.write_text('unsafe program.\nmain = _ = Sys.shutdownBegin Unit; '
                          '_ = if Sys.shutdownRequested Unit == 0 then print "software: no OS signal" '
                          'else error "software begin invented a signal"; '
                          f'Sys.shutdownComplete {code}.\n')
        image = tmp / f'software-complete-{code}.qa'
        build(source, image, tmp / f'software-complete-{code}-app')
        for harts in (1, 2):
            p = subprocess.run([str(host), '--yes', str(image)], cwd=tmp,
                               env={**os.environ, 'FPR_HARTS': str(harts), 'QOSP_SHUTDOWN_MS': '500'},
                               capture_output=True, text=True, timeout=2)
            text = p.stdout + p.stderr
            assert p.returncode == code and 'software: no OS signal' in text, p
            assert f'qosp: shutdown {"failed" if code else "complete"}' in text, text
        print(f'Portable shutdown: software completion {code} exits {code} without an OS signal HOLDS', flush=True)

    # The app returns normally after arming the software deadline. Its result
    # then fills host output: the watchdog must survive Host.run and cleanup.
    normal_pipe = tmp / 'normal-pipe.fpr'
    normal_pipe.write_text('unsafe program.\nmain = _ = Sys.ready Unit; _ = Sys.shutdownBegin Unit; "' +
                           'x' * 65536 + '".\n')
    image = tmp / 'normal-pipe.qa'
    build(normal_pipe, image, tmp / 'normal-pipe-app')
    work = tmp / 'normal-pipe'
    work.mkdir()
    p = subprocess.Popen([str(host), '--yes', str(image)], cwd=work,
                         env={**os.environ, 'FPR_HARTS': '2',
                              'QOSP_READY_FILE': str(work / 'ready'), 'QOSP_SHUTDOWN_MS': '250'},
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    began = time.monotonic()
    try:
        status = p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        raise AssertionError('normal return disabled the deadline before blocked host output')
    elapsed = time.monotonic() - began
    pending = array.array('i', [0])
    fcntl.ioctl(p.stdout.fileno(), termios.FIONREAD, pending, True)
    p.stdout.close()
    assert status == 124 and elapsed < 1.5 and pending[0] >= 8192, (status, elapsed, pending[0])
    assert not (work / 'ready').exists(), 'app did not return through Host.run before timeout'
    print('Portable shutdown: normal return retains the deadline through full host output HOLDS', flush=True)

    for name, action, want in (
        ('refused', 'if Sys.shutdownRequested Unit != 0 then Sys.shutdownComplete 1 else _ = Sys.sleepUs 1000; hold n', 1),
        ('stuck', '_ = Sys.sleepUs 1000; hold n', 124),
    ):
        src = tmp / f'{name}.fpr'
        src.write_text(f'unsafe program.\nhold n = {action}.\nmain = _ = inputPoll 0; _ = Sys.ready Unit; hold 0.\n')
        image = tmp / f'{name}.qa'
        build(src, image, tmp / f'{name}-app')
        work = tmp / name
        work.mkdir()
        status, elapsed, text = stop(start(host, image, work, 2, timeout_ms=250, tty=True), repeat=True)
        assert status == want and elapsed < 1.5, (status, elapsed, text)
        if want == 1:
            assert 'qosp: shutdown failed' in text, text
        print(f'Portable shutdown: {name} acknowledgement exits {want} within deadline HOLDS', flush=True)

    # The deadline must not need to log to a full pipe. This app publishes
    # readiness, then blocks in output while neither stdout nor stderr drains.
    flooded = tmp / 'flooded.fpr'
    flooded.write_text('unsafe program.\nhold n = _ = print "' + 'x' * 4096 +
                       '"; hold n.\nmain = _ = Sys.ready Unit; hold 0.\n')
    image = tmp / 'flooded.qa'
    build(flooded, image, tmp / 'flooded-app')
    work = tmp / 'flooded'
    work.mkdir()
    ready = work / 'ready'
    p = subprocess.Popen([str(host), '--yes', str(image)], cwd=work,
                         env={**os.environ, 'FPR_HARTS': '2',
                              'QOSP_READY_FILE': str(ready), 'QOSP_SHUTDOWN_MS': '250'},
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline, previous, stable = time.monotonic() + 10, 0, 0
    while time.monotonic() < deadline:
        assert p.poll() is None, f'flooding app exited early: {p.returncode}'
        pending = array.array('i', [0])
        fcntl.ioctl(p.stdout.fileno(), termios.FIONREAD, pending, True)
        stable = stable + 1 if pending[0] >= 8192 and pending[0] == previous else 0
        previous = pending[0]
        if stable >= 3 and ready.exists() and ready.read_text().strip() == str(p.pid):
            break
        time.sleep(.05)
    else:
        p.kill()
        p.wait()
        raise AssertionError('output did not fill before deadline probe')
    began = time.monotonic()
    p.send_signal(signal.SIGTERM)
    try:
        status = p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        raise AssertionError('full stderr pipe blocked forced shutdown')
    elapsed = time.monotonic() - began
    p.stdout.close()
    assert status == 124 and elapsed < 1.5, (status, elapsed, previous)
    print('Portable shutdown: full stderr pipe cannot block the forced deadline HOLDS', flush=True)
