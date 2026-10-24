#!/usr/bin/env python3
"""Run one service check, owning every subprocess group it creates.

This wrapper is private to check-services.py. Only the test interpreter's Popen
is wrapped; application/runtime subprocess behavior is unchanged. Each direct
child owns a session, including helpers that already requested one. Shell/make
children inherit their tracked session. The parent can recover these group IDs
if the interpreter itself must be killed.
"""
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import threading

PROCESS_POPEN = subprocess.Popen


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value) + '\n')
    temporary.replace(path)


def stop_sessions(sessions):
    if not sessions:
        return
    # GNU timeout/shells may make another process group inside our session.
    # Find those groups too, without reading any process arguments. Linux CI
    # containers need no procps package; macOS uses the system ps inventory.
    groups = set(sessions)
    if Path('/proc').is_dir():
        pids = [int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit()]
    else:
        # Bypass OwnedPopen here: inventory must not recursively track itself.
        with PROCESS_POPEN(['ps', '-axo', 'pid='], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True) as process:
            output, error = process.communicate(timeout=10)
            if process.returncode:
                raise RuntimeError('cannot inventory owned sessions: ' + error)
        pids = [int(p) for p in output.split()]
    for pid in pids:
        try:
            if os.getsid(pid) in sessions:
                groups.add(os.getpgid(pid))
        except (ProcessLookupError, PermissionError):
            pass
    for group in groups:
        if not isinstance(group, int) or group <= 1:
            raise ValueError('invalid process group')
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass


def stop_groups(path, worker=None):
    try:
        record = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return
    if worker is not None and record['worker'] != worker:
        raise ValueError('process registry belongs to another worker')
    stop_sessions(set(record['groups']))


def main():
    script, registry = sys.argv[1:]
    path = Path(registry)
    original = subprocess.Popen
    children = []
    lock = threading.Lock()
    record = {'worker': os.getpid(), 'groups': []}
    publishing = {'busy': False, 'signal': None}
    save(path, record)

    class OwnedPopen(original):
        def __init__(self, *args, **kwargs):
            # Publish before handling termination, so the supervisor always
            # knows about a successfully spawned group (even during cancellation).
            with lock:
                publishing['busy'] = True
                try:
                    kwargs['start_new_session'] = True
                    super().__init__(*args, **kwargs)
                    children.append(self)
                    record['groups'].append(self.pid)
                    try:
                        save(path, record)
                    except BaseException:
                        stop_sessions({self.pid})
                        original.wait(self)
                        raise
                finally:
                    publishing['busy'] = False
                    pending = publishing['signal']
                    publishing['signal'] = None
                    if pending:
                        os.kill(os.getpid(), pending)

        def wait(self, *args, **kwargs):
            status = super().wait(*args, **kwargs)
            with lock:
                if self.pid in record['groups']:
                    # A completed command cannot leave background descendants.
                    # Retire the session immediately so IDs cannot become stale.
                    stop_sessions({self.pid})
                    record['groups'].remove(self.pid)
                    save(path, record)
            return status

    def terminate(sig, frame):
        if publishing['busy']:
            publishing['signal'] = sig
            return
        raise SystemExit(128 + sig)

    subprocess.Popen = OwnedPopen
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    sys.argv = [script]
    sys.path.insert(0, str(Path(script).resolve().parent))
    try:
        if script.endswith('.py'):
            runpy.run_path(script, run_name='__main__')
        else:
            subprocess.run(['sh', script], check=True)
    finally:
        # Ignore further termination while cleaning up, then reap direct children.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        subprocess.Popen = original
        stop_groups(path, worker=os.getpid())
        for child in children:
            child.wait()


if __name__ == '__main__':
    main()
