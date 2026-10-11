#!/usr/bin/env python3
"""Actual appliance scripts: concurrency, readiness, restart limits and teardown.

Uses a recording child and real sessions/signals. The optional real-host leg
runs a prebuilt portableshutdown.qa through the actual qosp-session script.
The C helper supplies the same advisory lock on Linux and macOS.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
PACKAGE = HERE / 'package/qosp'
ACTIVE = []


def eventually(predicate, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.05)
    assert predicate(), 'lifecycle state did not settle'


def helpers(out):
    guard = out / 'guard'
    subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(PACKAGE / 'qosp-service-guard.c'), '-o', str(guard)], check=True)
    # macOS has setsid(2) but no setsid command. Preserve the child's PID across
    # exec, as BusyBox setsid does when its caller is not a process-group leader.
    detach = out / 'detach'
    detach.write_text('#!' + sys.executable + '\nimport os,sys\nos.setsid()\nos.execvp(sys.argv[1],sys.argv[1:])\n')
    detach.chmod(0o755)
    return guard, detach


def check(out):
    guard, detach = helpers(out)
    runner = out / 'runner'
    runner.write_text('''#!PYTHON
import os,signal,time
from pathlib import Path
base=Path(os.environ['CASE_DIR'])
count=base/'launches'
attempt=int(count.read_text())+1 if count.exists() else 1
count.write_text(str(attempt))
with (base/'pids').open('a') as f: f.write(str(os.getpid())+'\\n')
mode=os.environ.get('MODE','ready')
def stop(sig,frame):
    (base/'terminated').write_text(str(os.getpid()))
    raise SystemExit(7 if mode=='fail-stop' else 0)
signal.signal(signal.SIGTERM,signal.SIG_IGN if mode=='ignore-stop' else stop)
if mode=='crash' or (mode=='recover' and attempt==1): raise SystemExit(42)
if mode=='late-ready': time.sleep(5)
if mode!='no-ready':
    ready=Path(os.environ['QOSP_READY_FILE'])
    ready.write_text('123' if mode=='wrong-ready' else str(os.getpid()))
while True: time.sleep(.1)
'''.replace('PYTHON', sys.executable))
    runner.chmod(0o755)

    class Case:
        def __init__(self, name, mode='ready', retries='0', ready='2'):
            self.path = out / name
            self.path.mkdir()
            self.run = self.path / 'run'
            self.env = dict(os.environ, CASE_DIR=str(self.path), MODE=mode,
                            QOSP_RUN_DIR=str(self.run), QOSP_LOG=str(self.path / 'service.log'),
                            QOSP_TTY='/dev/null', QOSP_SERVICE_LIB=str(PACKAGE / 'qosp-service.sh'),
                            QOSP_SERVICE_GUARD=str(guard), QOSP_SUPERVISOR=str(PACKAGE / 'qosp-supervise'),
                            QOSP_SESSION=str(runner), QOSP_SETSID=str(detach),
                            QOSP_READY_TIMEOUT_SEC=ready, QOSP_STOP_TIMEOUT_SEC='1',
                            QOSP_KILL_TIMEOUT_SEC='1', QOSP_RESTART_MAX=retries,
                            QOSP_RESTART_DELAY_SEC='1', QOSP_RESTART_DELAY_MAX_SEC='2')
            self.env.pop('QOSP_SERVICE_GUARDED', None)
            self.env.pop('QOSP_READY_FILE', None)
            ACTIVE.append(self)

        def command(self, operation, expect=0, timeout=20):
            p = subprocess.run(['sh', str(PACKAGE / 'S99qosp'), operation], env=self.env,
                               capture_output=True, text=True, timeout=timeout)
            log = (self.path / 'service.log').read_text() if (self.path / 'service.log').exists() else ''
            assert p.returncode == expect, (operation, p.returncode, p.stdout, p.stderr, log)
            return p.stdout + p.stderr

        def launches(self):
            return int((self.path / 'launches').read_text())

        def pid(self, name):
            return int((self.run / 'owner' / (name + '.pid')).read_text())

        def assert_quiet(self):
            assert not (self.run / 'owner').exists(), self.run
            assert not (self.run / 'ready').exists(), self.run

    normal = Case('normal')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: normal.command('start'), range(4)))
    first = normal.pid('child')
    assert normal.launches() == 1
    normal.command('start')
    assert normal.pid('child') == first
    normal.command('status')
    normal.command('stop')
    assert (normal.path / 'terminated').exists()
    normal.command('status', expect=3)
    normal.command('stop')
    normal.assert_quiet()
    print('Service: concurrent/duplicate start, ready status, graceful stop and repeat stop HOLDS', flush=True)

    recover = Case('recover', mode='recover', retries='2')
    began = time.monotonic()
    recover.command('start')
    assert recover.launches() == 2 and time.monotonic() - began >= 1
    recover.command('stop')
    recover.assert_quiet()
    print('Service: an unexpected exit restarts after backoff, later ready child stops HOLDS', flush=True)

    crashing = Case('crashing', mode='crash', retries='2')
    began = time.monotonic()
    crashing.command('start', expect=1)
    assert crashing.launches() == 3 and time.monotonic() - began >= 3
    assert 'restart-budget-exhausted' in crashing.command('status', expect=3)
    crashing.assert_quiet()
    crashing.env['MODE'] = 'ready'
    crashing.command('restart')
    crashing.command('stop')
    crashing.assert_quiet()
    print('Service: finite restart budget latches failure; administrative restart clears it HOLDS', flush=True)

    for mode in ('no-ready', 'wrong-ready'):
        missing = Case(mode, mode=mode, ready='1')
        missing.run.mkdir()
        (missing.run / 'ready').write_text('stale marker')
        missing.command('start', expect=1)
        assert missing.launches() == 1 and (missing.path / 'terminated').exists()
        missing.assert_quiet()
    print('Service: missing, stale or wrong-PID readiness cannot pass startup HOLDS', flush=True)

    for mode in ('fail-stop', 'ignore-stop'):
        failing = Case(mode, mode=mode)
        failing.command('start')
        began = time.monotonic()
        failing.command('stop', expect=1)
        assert time.monotonic() - began < 7
        assert 'failed' in failing.command('status', expect=3)
        failing.assert_quiet()
    print('Service: failed shutdown and TERM refusal are failures; escalation is bounded HOLDS', flush=True)

    foreign = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        stale = Case('stale')
        owner = stale.run / 'owner'
        owner.mkdir(parents=True)
        for name in ('supervisor', 'child'):
            (owner / (name + '.pid')).write_text(str(foreign.pid))
            (owner / (name + '.identity')).write_text('wrong start token')
        stale.command('start')
        stale.command('stop')
        assert foreign.poll() is None
        stale.assert_quiet()
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)
    print('Service: stale/reused PID records do not signal an unrelated process HOLDS', flush=True)

    orphan = Case('orphan')
    orphan.command('start')
    os.kill(orphan.pid('supervisor'), signal.SIGKILL)
    eventually(lambda: not subprocess.run(['sh', str(PACKAGE / 'S99qosp'), 'status'],
               env=orphan.env, capture_output=True).returncode == 0)
    orphan.command('start', expect=1)
    orphan.command('stop', expect=1)
    assert 'orphan-shutdown-unconfirmed' in orphan.command('status', expect=3)
    orphan.assert_quiet()
    orphan.command('restart')
    orphan.command('stop')
    print('Service: a dead supervisor cannot allow another writer; orphan shutdown is unconfirmed and explicit restart is safe HOLDS', flush=True)

    frozen = Case('frozen-supervisor', mode='ignore-stop')
    frozen.command('start')
    os.kill(frozen.pid('supervisor'), signal.SIGSTOP)
    began = time.monotonic()
    frozen.command('stop', expect=1)
    assert time.monotonic() - began < 8
    assert 'supervisor-stop-timeout' in frozen.command('status', expect=3)
    frozen.env['MODE'] = 'ready'
    frozen.command('start')
    frozen.command('stop')
    frozen.assert_quiet()
    print('Service: an unresponsive supervisor gets bounded outer escalation; later start is safe HOLDS', flush=True)

    interrupted = Case('interrupted', mode='late-ready', ready='10')
    starter = subprocess.Popen(['sh', str(PACKAGE / 'S99qosp'), 'start'], env=interrupted.env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    eventually(lambda: (interrupted.run / 'owner/child.pid').exists())
    interrupted.command('stop')
    stdout, stderr = starter.communicate(timeout=5)
    assert starter.returncode == 1, (stdout, stderr)
    interrupted.assert_quiet()
    print('Service: stop interrupts startup without a restart or held control lock HOLDS', flush=True)

    for target in ('supervisor.identity', 'child.pending', 'child.identity'):
        failure = Case('record-' + target, mode='ignore-stop')
        library = failure.path / 'fault-service.sh'
        # Inject an I/O failure at the record boundary without replacing the
        # supervisor's policy. Delay the child fault until its handler is live.
        library.write_text((PACKAGE / 'qosp-service.sh').read_text() + '''
qosp_write_record() {
    case "$1" in
        */TARGET)
            if [ "TARGET" = child.identity ]; then
                n=100
                while [ ! -s "$CASE_DIR/pids" ] && [ "$n" -gt 0 ]; do sleep 0.01; n=$((n - 1)); done
            fi
            return 1 ;;
    esac
    printf '%s\\n' "$2" > "$1"
}
'''.replace('TARGET', target))
        failure.env['QOSP_SERVICE_LIB'] = str(library)
        began = time.monotonic()
        failure.command('start', expect=1)
        assert time.monotonic() - began < 8
        if target == 'child.identity':
            assert failure.launches() == 1
            child = int((failure.path / 'pids').read_text().strip())
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError('unrecorded child survived bounded teardown')
        else:
            assert not (failure.path / 'launches').exists()
        failure.assert_quiet()
        failure.env['QOSP_SERVICE_LIB'] = str(PACKAGE / 'qosp-service.sh')
        failure.env['MODE'] = 'ready'
        failure.command('restart')
        failure.command('stop')
        failure.assert_quiet()
    print('Service: ownership record failures refuse before launch or bound child teardown; later explicit restart is safe HOLDS', flush=True)

    uncertain = Case('uncertain-owner')
    owner = uncertain.run / 'owner'
    owner.mkdir(parents=True)
    (owner / 'child.pending').write_text('pending')
    (owner / 'child.pid').write_text(str(os.getpid()))
    (owner / 'child.identity').write_text('incomplete start token')
    assert 'unconfirmed' in uncertain.command('start', expect=1)
    assert 'unconfirmed' in uncertain.command('stop', expect=1)
    uncertain.command('status', expect=1)
    assert not (uncertain.path / 'launches').exists()
    # No child was launched in this constructed fixture. Only the test can
    # establish that fact; the production scripts must retain uncertainty.
    (owner / 'child.pending').unlink()
    (owner / 'child.pid').unlink()
    (owner / 'child.identity').unlink()
    owner.rmdir()
    uncertain.command('restart')
    uncertain.command('stop')
    uncertain.assert_quiet()
    print('Service: incomplete launch ownership cannot be reclaimed as a stale instance HOLDS', flush=True)

    for mode, missing in (('ready', False), ('fail-stop', False), ('ready', True)):
        lost = Case('lost-final-' + mode + ('-missing' if missing else ''), mode=mode)
        library = lost.path / 'fault-service.sh'
        library.write_text((PACKAGE / 'qosp-service.sh').read_text() + '''
qosp_state() {
    case "$1" in stopped|failed*) ACTION; return 1 ;; esac
    printf '%s\\n' "$*" > "$STATE_FILE.tmp.$$" && mv -f "$STATE_FILE.tmp.$$" "$STATE_FILE"
}
'''.replace('ACTION', 'rm -f "$STATE_FILE"' if missing else ':'))
        lost.env['QOSP_SERVICE_LIB'] = str(library)
        lost.command('start')
        assert 'unconfirmed' in lost.command('stop', expect=1)
        lost.assert_quiet()
        lost.env['QOSP_SERVICE_LIB'] = str(PACKAGE / 'qosp-service.sh')
        lost.env['MODE'] = 'ready'
        lost.command('restart')
        lost.command('stop')
        lost.assert_quiet()
    empty = Case('never-started')
    empty.command('stop')
    print('Service: lost final shutdown state refuses a clean result; a truly absent instance stops idempotently HOLDS', flush=True)

    invalid = Case('invalid-settings')
    for value in ('-1', 'fast', '08', '999999999999999999999999'):
        invalid.env['QOSP_STOP_TIMEOUT_SEC'] = value
        invalid.command('start', expect=1)
        assert not (invalid.path / 'launches').exists()
    print('Service: malformed and excessive lifecycle settings refuse before launch HOLDS', flush=True)


def real_check(out, host, archive):
    guard, detach = helpers(out)

    class RealCase:
        def __init__(self, harts):
            self.path = out / f'real-{harts}'
            self.path.mkdir()
            self.run = self.path / 'run'
            self.log = self.path / 'service.log'
            share = self.path / 'share'
            share.mkdir()
            self.env = dict(os.environ, QOSP_RUN_DIR=str(self.run), QOSP_LOG=str(self.log),
                            QOSP_TTY='/dev/null', QOSP_SERVICE_LIB=str(PACKAGE / 'qosp-service.sh'),
                            QOSP_SERVICE_GUARD=str(guard), QOSP_SUPERVISOR=str(PACKAGE / 'qosp-supervise'),
                            QOSP_SESSION=str(PACKAGE / 'qosp-session'), QOSP_SETSID=str(detach),
                            QOSP_BIN=str(host), QOSP_APP=str(archive), QOSP_SHARE=str(share),
                            QOSP_STATE=str(self.path / 'state'), QOSP_NO_WAIT_DRI='1',
                            QOSP_READY_TIMEOUT_SEC='30', QOSP_STOP_TIMEOUT_SEC='7',
                            QOSP_KILL_TIMEOUT_SEC='1', QOSP_RESTART_MAX='0',
                            QOSP_RESTART_DELAY_SEC='1', QOSP_RESTART_DELAY_MAX_SEC='2',
                            QOSP_SHUTDOWN_MS='5000', FPR_HARTS=str(harts), FPR_PORT='0')
            for name in ('QOSP_SERVICE_GUARDED', 'QOSP_READY_FILE', 'FPR_DISK'):
                self.env.pop(name, None)
            ACTIVE.append(self)

        def command(self, operation, expect=0):
            p = subprocess.run(['sh', str(PACKAGE / 'S99qosp'), operation], env=self.env,
                               capture_output=True, text=True, timeout=45)
            text = self.log.read_text() if self.log.exists() else ''
            assert p.returncode == expect, (operation, p.returncode, p.stdout, p.stderr, text)
            return text

    for harts in (1, 2):
        case = RealCase(harts)
        for replay in (False, True):
            position = len(case.log.read_text()) if case.log.exists() else 0
            case.command('start')
            child = (case.run / 'owner/child.pid').read_text().strip()
            assert (case.run / 'ready').read_text().strip() == child
            case.command('status')
            began = time.monotonic()
            text = case.command('stop')[position:]
            assert time.monotonic() - began < 7, text
            assert 'storage drained and flushed' in text and 'qosp: shutdown complete' in text, text
            assert (case.run / 'state').read_text().strip() == 'stopped', text
            if replay:
                assert 'portableshutdown: replayed=committed' in text, text
            else:
                assert 'portableshutdown: fresh' in text, text
            assert not (case.run / 'owner').exists() and not (case.run / 'ready').exists()
            case.command('status', expect=3)
        print(f'Service real host: {harts} hart(s), qosp-session readiness, durable shutdown and fresh-process replay HOLDS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, help='prebuilt qosp executable for the integrated leg')
    parser.add_argument('--archive', type=Path, help='prebuilt tests/portableshutdown.fpr .qa archive')
    parser.add_argument('--real-only', action='store_true', help='run only the integrated leg')
    args = parser.parse_args()
    if bool(args.host) != bool(args.archive) or (args.real_only and not args.host):
        parser.error('--host and --archive are required together; --real-only needs both')
    if args.host:
        args.host, args.archive = args.host.resolve(), args.archive.resolve()
        if not args.host.is_file() or not args.archive.is_file():
            parser.error('--host and --archive must name existing files')
    with tempfile.TemporaryDirectory(prefix='qosp-service-check-') as temp:
        try:
            if not args.real_only:
                check(Path(temp))
            if args.host:
                real_check(Path(temp), args.host, args.archive)
        finally:
            # Failed assertions must not leave detached fixture processes alive.
            for case in ACTIVE:
                if (case.run / 'owner').exists():
                    subprocess.run(['sh', str(PACKAGE / 'S99qosp'), 'stop'], env=case.env,
                                   capture_output=True, timeout=10)
