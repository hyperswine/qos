#!/usr/bin/env python3
"""Isolated QOS service checks, bounded parallelism and retained failure logs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from service_checks import CHECKS
from service_worker import stop_groups

ROOT = Path(__file__).resolve().parents[1]
BUILD_ENV = {'MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES', 'BUILD', 'QA_OUT', 'QOSP_OUT',
             'QOSP_ES_OUT', 'KERNEL', 'DISK', 'PDISK', 'PLUG_OUT', 'IMAGE', 'PROG',
             'SYSTEM', 'APP_HOST', 'HARTS', 'QOSHARTS', 'QOSSLAB', 'QOSSTACK',
             'FPRBUILD_EXTRA', 'QOSCFLAGS_EXTRA', 'NATIVE_CFLAGS_EXTRA'}


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def snapshot(source, destination, exclude=None):
    """Copy current tracked/untracked inputs, not Git metadata or ignored state.
    Never hard-link: a fixture rewrite must not mutate the source checkout."""
    names = subprocess.check_output(['git', 'ls-files', '-z', '-c', '-o', '--exclude-standard'], cwd=source).split(b'\0')
    digest = hashlib.sha256()
    count = 0
    for name in sorted(set(names) - {b''}):
        relative = Path(os.fsdecode(name))
        path = source / relative
        if exclude and path.is_relative_to(exclude):
            continue
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(source.resolve()):
            raise ValueError(f'snapshot input escapes checkout: {relative}')
        data = path.read_bytes()
        digest.update(name + b'\0' + hashlib.sha256(data).digest())
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        shutil.copystat(path, target)
        count += 1
    return {'sha256': digest.hexdigest(), 'files': count}


class Runner:
    def __init__(self, output, compiler, workers):
        self.output, self.compiler, self.workers = output, compiler, workers
        self.active = {}
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.results = {}
        self.began = time.monotonic()

    def environment(self, tree, work):
        # Runtime/device paths and injected faults must not escape into a run.
        # Tests install their own explicit variants after this clean baseline.
        env = {k: v for k, v in os.environ.items()
               if k not in BUILD_ENV and not k.startswith(('FPR_', 'FPRD_', 'QOSP_', 'QOS_BLK_', 'QOS_STORE_TEST'))}
        return dict(env, FPRISC_ROOT=str(self.compiler), FPR_HOME=str(tree),
                    FPR_PATH=str(self.compiler), FPR_FOREIGN=str(tree / 'core/foreign.fpr'),
                    FPR_PORT='0', FPR_DISK=str(work / 'default.disk'),
                    XDG_CACHE_HOME=str(work / 'cache'),
                    TMPDIR=str(work / 'tmp'), TMP=str(work / 'tmp'), TEMP=str(work / 'tmp'))

    def prepare(self):
        tree = self.output / 'snapshot'
        metadata = snapshot(ROOT, tree, self.output)
        write_json(self.output / 'snapshot.json', metadata)
        # Preflight once. All check copies use this already-built compiler.
        # Also seed the default host for checks (qsys) that assume it exists.
        work = self.output / 'prepare'
        (work / 'tmp').mkdir(parents=True)
        env = self.environment(tree, work)
        with (self.output / 'prepare.log').open('w') as log:
            for command in (['make', '-s', '-C', self.compiler, 'fpr'],
                            ['make', '-s', '-C', tree / 'qos', 'portable']):
                if self.cancelled.is_set():
                    raise RuntimeError('preparation cancelled')
                registry = work / 'no-worker-registry.json'
                with self.lock:
                    process = subprocess.Popen(command, env=env, stdout=log,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                    self.active[process.pid] = (process, registry)
                if self.cancelled.is_set():
                    self.stop(process, registry)
                try:
                    code = process.wait(timeout=300)
                    if code:
                        raise subprocess.CalledProcessError(code, command)
                finally:
                    self.stop(process, registry)
                    with self.lock:
                        self.active.pop(process.pid, None)

    def report(self):
        write_json(self.output / 'results.json', {
            'workers': self.workers, 'seconds': time.monotonic() - self.began,
            'compiler': str(self.compiler), 'checks': self.results})

    def one(self, check):
        work = self.output / 'jobs' / check.name
        work.mkdir(parents=True)
        (work / 'tmp').mkdir()
        tree = work / 'tree'
        began = time.monotonic()
        print(f'{check.name}: starting' + (' (exclusive)' if check.exclusive else ''), flush=True)
        registry = work / 'processes.json'
        result = {'status': 'failed', 'exclusive': check.exclusive, 'script': check.script}
        p = None
        try:
            if self.cancelled.is_set():
                result['status'] = 'cancelled'
                return result
            shutil.copytree(self.output / 'snapshot', tree)
            env = self.environment(tree, work)
            with (work / 'output.log').open('w') as log:
                with self.lock:
                    if self.cancelled.is_set():
                        result['status'] = 'cancelled'
                        return result
                    p = subprocess.Popen([sys.executable, tree / 'tools/service_worker.py',
                                          check.script, registry], cwd=tree, env=env,
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True)
                    self.active[p.pid] = (p, registry)
                try:
                    code = p.wait(timeout=check.timeout)
                    result.update(status='cancelled' if self.cancelled.is_set() else ('ok' if code == 0 else 'failed'), exit=code)
                except subprocess.TimeoutExpired:
                    result['status'] = 'timeout'
                    self.stop(p, registry)
        except BaseException:
            result['error'] = traceback.format_exc()
        finally:
            if p:
                self.stop(p, registry)
                with self.lock:
                    self.active.pop(p.pid, None)
            result['seconds'] = time.monotonic() - began
        return result

    @staticmethod
    def stop(process, registry):
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            # A shell/make leader may have exited while its children kept running.
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stop_groups(registry, worker=process.pid)

    def cancel(self, sig=None, frame=None):
        self.cancelled.set()
        with self.lock:
            active = list(self.active.values())
        for process, registry in active:
            self.stop(process, registry)

    def run(self, checks):
        def record(check, result):
            self.results[check.name] = result
            self.report()
            print(f'{check.name}: {result["status"]} ({result["seconds"]:.1f} s)', flush=True)
            if result['status'] != 'ok':
                print(f'  log: {self.output / "jobs" / check.name / "output.log"}', flush=True)
        # All exclusives finish before the pool starts. Their deadlines/assertions
        # are unchanged and they never share this runner with another check.
        for check in checks:
            if check.exclusive:
                record(check, self.one(check))
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            pending = {pool.submit(self.one, c): c for c in checks if not c.exclusive}
            for future in as_completed(pending):
                record(pending[future], future.result())
        return all(r['status'] == 'ok' for r in self.results.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-j', '--jobs', type=int, default=int(os.environ.get('QOS_CHECK_JOBS', '2')))
    ap.add_argument('--output', type=Path, help='new directory to retain private workspaces/logs/results')
    ap.add_argument('--only', action='append', choices=[c.name for c in CHECKS])
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--verdict', choices=[c.name for c in CHECKS], help='read one check status for check-all.sh')
    ap.add_argument('--results', type=Path)
    args = ap.parse_args()
    if args.verdict:
        if not args.results:
            ap.error('--verdict requires --results')
        try:
            result = json.loads(args.results.read_text())['checks'].get(args.verdict)
        except (OSError, ValueError, KeyError) as error:
            ap.exit(1, f'{args.verdict}: no valid completion record: {error}\n')
        if not result or result['status'] != 'ok':
            ap.exit(1, f'{args.verdict}: did not pass; see {args.results}\n')
        return
    if not 1 <= args.jobs <= 4:
        ap.error('--jobs must be between 1 and 4 (default 2)')
    checks = [c for c in CHECKS if not args.only or c.name in args.only]
    if args.list:
        print('\n'.join(c.name + (' (exclusive)' if c.exclusive else '') for c in checks))
        return
    compiler = subprocess.check_output([sys.executable, ROOT / 'qos.py', 'fprisc', '--print'], text=True).strip()
    if args.output:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=False)
    else:
        parent = ROOT / 'build/service-checks'
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    print(f'check-services: {len(checks)} checks, {args.jobs} worker(s), output {output}', flush=True)
    runner = Runner(output, Path(compiler), args.jobs)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, runner.cancel)
    try:
        runner.prepare()
        success = runner.run(checks)
    except BaseException:
        runner.cancel()
        runner.report()
        raise
    ap.exit(0 if success and not runner.cancelled.is_set() else 1)


if __name__ == '__main__':
    main()
