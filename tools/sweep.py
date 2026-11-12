#!/usr/bin/env python3
"""sweep.py -- check-all.sh's legs, several at a time, with times.

check-all.sh stays the list of legs and the serial reference; this reads the
legs out of it and runs each exactly as written:

  * every worker has a private copy of the tree, so two legs never share
    build/, app.qa or a disk image; a leg marked `# sweep: serial`, and any
    leg that names a fixed /tmp file, runs on one lane in file order;
  * the service checks run once beside the workers (tools/check-services.py),
    and their legs read its verdicts;
  * compiled units and runtime objects are content-addressed, so every tree
    shares one cache of each (build/units, QOS_OBJ_CACHE);
  * --since REF runs only the legs a change can reach (see `affected`), and
    reports the rest as not run, never as passed;
  * a leg that fails is run again alone, since a deadline can be missed only
    because other legs took the cores; both verdicts are recorded;
  * results.json records each leg's status and seconds.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
LEG = 'echo "== '
SUMMARY = '# ---- sweep summary'
PRELUDE = r'''set -euo pipefail
ran() { "$@" || true; }
leg_failed() { echo "** LEG FAILED"; : > "$LEG_MARK.failed"; }
leg_skipped() { echo "skipped ($1)"; printf '%s\n' "$1" > "$LEG_MARK.skipped"; }
service_leg() { python3 tools/check-services.py --verdict "$1" --results "$SWEEP_SERVICES/results.json"; }
ROOT="$(pwd)"
'''
# A change to any of these reaches every leg: narrowing is only for leaves.
LEAVES = ('tests/', 'tools/', 'docs/')
WORD = re.compile(r'[\w-]+')
USE = re.compile(r'use\s+"([^"#]+)')


def leaves():
    """How a file under tests/ or tools/ is named: a file directly in either
    by its stem as a word (a path, an import, a name in a table of checks);
    a nested one, whose stem is often an ordinary word (tools/qos/build.fpr),
    only by its last two path components."""
    names = subprocess.check_output(['git', 'ls-files', '-c', '-o', '--exclude-standard', 'tests', 'tools'], cwd=ROOT, text=True)
    words, tails = {}, {}
    for name in names.split('\n'):
        if name.count('/') == 1:
            words.setdefault(Path(name).stem, set()).add(name)
        elif name:
            tails['/'.join(name.split('/')[-2:])] = name
    return words, tails


def legs_of(text):
    """[(name, body, serial, follows)] in file order, each body as written.
    `follows`: the leg uses what the leg before it built, so the two run
    one after the other in one tree."""
    lines = text.splitlines()
    end = next(i for i, line in enumerate(lines) if line.startswith(SUMMARY))
    starts = [i for i, line in enumerate(lines[:end]) if line.startswith(LEG)]
    legs = []
    for n, start in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else end
        body = '\n'.join(lines[start:stop])
        name = lines[start][len(LEG):].split(' ==', 1)[0]
        tag = lines[start - 1].strip() if start else ''
        legs.append((name, body, tag == '# sweep: serial' or '/tmp/' in body, tag == '# sweep: with previous'))
    return legs


def reach(text, table, seen):
    """Add every test and tool `text` can name, transitively.

    Naming is by `leaves`.  It over-reaches where a stem is also an ordinary
    word, which only runs more legs.
    """
    words, tails = table
    named = {path for word in set(WORD.findall(text)) for path in words.get(word, ())}
    named |= {path for tail, path in tails.items() if tail in text}
    for path in named - seen:
        if path in seen:
            continue
        seen.add(path)
        try:
            inner = (ROOT / path).read_text(errors='replace')
        except OSError:
            continue
        reach(inner, table, seen)
        if path.endswith('.fpr'):
            for used in USE.findall(inner):
                target = os.path.normpath(os.path.join(os.path.dirname(path), used + '.fpr'))
                if target not in seen and (ROOT / target).is_file():
                    seen.add(target)
                    reach((ROOT / target).read_text(errors='replace'), table, seen)


def reach_table(legs, services):
    """For each leg, the tests and tools it can name."""
    table = leaves()
    reached = []
    for _, body, _, _ in legs:
        seen = set()
        text = body
        for name in re.findall(r'service_leg ([\w-]+)', body):
            text += f' check-services service_checks service_worker {services.get(name, "")}'
        reach(text, table, seen)
        reached.append(seen)
    return reached


def affected(legs, changed, services, reached=None):
    """Indexes of the legs `changed` can reach, and why.

    A path outside tests/, tools/ and docs/ (a program, the runtime, a
    makefile, a lock) reaches everything, and so does a tool a makefile
    names.  docs/ and *.md reach nothing.  Any other test or tool reaches
    the legs that name it, directly or through a script or a `use`; one that
    no leg names reaches everything, since nothing here can say what it feeds.
    """
    everything = set(range(len(legs)))
    makefiles = ' '.join(path.read_text(errors='replace') for path in
                         [ROOT / 'Makefile', ROOT / 'qos/Makefile', *ROOT.glob('*.mk'), *ROOT.glob('hal/*/*.mk')] if path.is_file())
    built = set(WORD.findall(makefiles))
    reached = reached if reached is not None else reach_table(legs, services)
    wanted, why = set(), []
    for path in sorted(changed):
        if path.startswith('docs/') or path.endswith('.md'):
            continue
        if not path.startswith(LEAVES):
            return everything, [f'{path}: reaches every leg']
        if path.startswith('tools/') and Path(path).stem in built:
            return everything, [f'{path}: a makefile names it, so every leg runs']
        hit = {i for i, seen in enumerate(reached) if path in seen}
        if not hit:
            return everything, [f'{path}: no leg names it, so every leg runs']
        wanted |= hit
        why.append(f'{path}: {len(hit)} leg(s)')
    return wanted, why


def changed_since(ref):
    names = subprocess.check_output(['git', 'diff', '--name-only', ref], cwd=ROOT, text=True).split('\n')
    names += subprocess.check_output(['git', 'ls-files', '-o', '--exclude-standard'], cwd=ROOT, text=True).split('\n')
    return {n for n in names if n}


def service_scripts():
    spec = importlib.util.spec_from_file_location('service_checks', ROOT / 'tools/service_checks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {c.name: c.script for c in module.CHECKS}


class Sweep:
    def __init__(self, output, compiler, jobs, timeout):
        self.output, self.compiler, self.jobs, self.timeout = output, compiler, jobs, timeout
        self.lock = threading.Lock()
        self.results = {}
        self.active = set()
        self.cancelled = threading.Event()
        self.services = threading.Event()
        self.cancelled_early = True
        self.service_jobs = 2
        self.began = time.monotonic()

    def environment(self, tree, work):
        drop = ('FPR_', 'FPRD_', 'QOSP_', 'QOS_BLK_', 'QOS_STORE_TEST', 'CK_')
        env = {k: v for k, v in os.environ.items() if not k.startswith(drop) and k not in ('MAKEFLAGS', 'MFLAGS', 'BUILD', 'PROG')}
        return dict(env, FPRISC_ROOT=str(self.compiler), FPR_HOME=str(tree), FPR_PATH=str(self.compiler),
                    FPR_FOREIGN=str(tree / 'core/foreign.fpr'), FPR_DISK=str(work / 'default.disk'),
                    XDG_CACHE_HOME=str(work / 'cache'), CK_TMP=str(work / 'ck'),
                    TMPDIR=str(work / 'tmp'), TMP=str(work / 'tmp'), TEMP=str(work / 'tmp'),
                    QOS_OBJ_CACHE=str(self.output / 'objects'), SWEEP_SERVICES=str(self.output / 'services'))

    def call(self, command, cwd, env, log, timeout):
        with self.lock:
            if self.cancelled.is_set():
                return None
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            self.active.add(process)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return 'timeout'
        finally:
            self.stop(process)
            with self.lock:
                self.active.discard(process)

    @staticmethod
    def stop(process):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                continue
            # the leader is gone; its group may still hold children
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def cancel(self, *_):
        self.cancelled.set()
        with self.lock:
            active = list(self.active)
        for process in active:
            self.stop(process)

    def prepare(self, workers):
        from importlib import import_module
        snapshot = import_module('check-services').snapshot
        base = self.output / 'snapshot'
        write(self.output / 'snapshot.json', snapshot(ROOT, base, self.output))
        work = self.output / 'prepare'
        (work / 'tmp').mkdir(parents=True)
        env = self.environment(base, work)
        with (self.output / 'prepare.log').open('w') as log:
            for command in (['make', '-s', '-C', str(self.compiler), 'fpr'], ['make', '-s', '-C', str(base / 'qos'), 'portable']):
                if self.call(command, base, env, log, 900) != 0:
                    raise SystemExit(f'sweep: preparation failed: {" ".join(command)} (see {self.output / "prepare.log"})')
        for shared in ('units', 'objects'):
            (self.output / shared).mkdir()
        trees = []
        for n in range(workers):
            work = self.output / f'worker-{n}'
            tree = work / 'tree'
            shutil.copytree(base, tree, symlinks=True)
            for scratch in ('tmp', 'ck', 'cache'):
                (work / scratch).mkdir()
            # one unit cache for every tree: units are named by their content
            for build in ('build', '.qos/build'):
                (tree / build).mkdir(parents=True, exist_ok=True)
                (tree / build / 'units').symlink_to(self.output / 'units')
            trees.append((tree, work))
        return trees

    def run_services(self, env):
        try:
            with (self.output / 'services.log').open('w') as log:
                self.call([sys.executable, 'tools/check-services.py', '--jobs', str(self.service_jobs), '--output', str(self.output / 'services')],
                          ROOT, env, log, 3600)
        finally:
            self.services.set()

    def leg(self, index, name, body, tree, work, lane):
        mark = self.output / 'legs' / f'{index:03d}'
        script = mark.with_suffix('.sh')
        script.write_text(PRELUDE + body + '\n')
        for suffix in ('.failed', '.skipped'):
            mark.with_suffix(suffix).unlink(missing_ok=True)
        if 'service_leg' in body:
            self.services.wait()
        env = dict(self.environment(tree, work), LEG_MARK=str(mark))
        began = time.monotonic()
        with mark.with_suffix('.log').open('w') as log:
            code = self.call(['bash', str(script)], tree, env, log, self.timeout)
        if code is None:
            status = 'cancelled'
        elif code == 'timeout':
            status = 'timeout'
        elif mark.with_suffix('.failed').exists() or code != 0:
            status = 'failed'
        elif mark.with_suffix('.skipped').exists():
            status = 'skipped'
        else:
            status = 'passed'
        result = {'name': name, 'status': status, 'seconds': round(time.monotonic() - began, 1), 'lane': lane,
                  'log': str(mark.with_suffix('.log'))}
        if status == 'skipped':
            result['reason'] = mark.with_suffix('.skipped').read_text().strip()
        with self.lock:
            self.results[index] = result
            self.report()
        print(f'{status:8} {result["seconds"]:7.1f} s  {name}', flush=True)

    def report(self):
        write(self.output / 'results.json', {
            'jobs': self.jobs, 'seconds': round(time.monotonic() - self.began, 1), 'compiler': str(self.compiler),
            'legs': [self.results[i] for i in sorted(self.results)]})

    def run(self, legs, chosen, known=None, retry=True):
        (self.output / 'legs').mkdir()
        # a group is a leg and the legs that follow it; it runs in one tree
        groups = []
        for i in range(len(legs)):
            if legs[i][3] and groups:
                groups[-1].append(i)
            else:
                groups.append([i])
        groups = [g for g in groups if any(i in chosen for i in g)]
        serial = [g for g in groups if any(legs[i][2] for i in g)]
        free = [g for g in groups if not any(legs[i][2] for i in g)]
        if known:
            # longest first, so a ten-minute leg is not the one left running alone
            free.sort(key=lambda g: -sum(known.get(legs[i][0], 0) for i in g))
        trees = self.prepare(min(self.jobs, max(1, len(groups))))
        if any('service_leg' in legs[i][1] for g in groups for i in g):
            threading.Thread(target=self.run_services, args=(self.environment(ROOT, self.output / 'prepare'),), daemon=True).start()
        else:
            self.services.set()

        def worker(n):
            tree, work = trees[n]
            while not self.cancelled.is_set():
                with self.lock:
                    # lane 0 takes the serial legs first, in file order
                    queue = serial if n == 0 and serial else free
                    if not queue:
                        return
                    group = queue.pop(0)
                for index in group:
                    self.leg(index, legs[index][0], legs[index][1], tree, work, 'serial' if legs[index][2] else f'worker-{n}')

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(len(trees))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # A leg with a deadline can fail only because its neighbours took the
        # cores.  Run each failure again with nothing beside it; the record
        # keeps both verdicts, and the summary counts these apart.
        self.services.wait()
        again = [g for g in groups if any(self.results.get(i, {}).get('status') in ('failed', 'timeout') for i in g)]
        for group in again if retry else []:
            if self.cancelled.is_set():
                break
            first = {i: self.results[i]['status'] for i in group if i in self.results}
            for index in group:
                if 'service_leg' in legs[index][1]:
                    continue   # its verdict is the service run's, which is not repeated
                self.leg(index, legs[index][0], legs[index][1], trees[0][0], trees[0][1], 'alone')
                self.results[index]['first'] = first.get(index)
            self.report()


def write(path, value):
    partial = path.with_suffix('.tmp')
    partial.write_text(json.dumps(value, indent=2) + '\n')
    partial.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-j', '--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2), help='worker trees (default: half the cores)')
    ap.add_argument('--output', type=Path, required=True, help='a directory that does not exist yet')
    ap.add_argument('--since', metavar='REF', help='run only the legs a change since REF can reach')
    ap.add_argument('--only', action='append', default=[], metavar='TEXT', help='run legs whose name contains TEXT')
    ap.add_argument('--list', action='store_true', help='print the legs that would run, and why')
    ap.add_argument('--times', type=Path, metavar='RESULTS', help='an earlier results.json: start the longest legs first')
    ap.add_argument('--no-retry', action='store_true', help='do not run a failed leg again alone')
    ap.add_argument('--timeout', type=int, default=2400, help='seconds one leg may take')
    args = ap.parse_args()
    legs = legs_of((ROOT / 'check-all.sh').read_text())
    chosen, why = set(range(len(legs))), []
    if args.since:
        chosen, why = affected(legs, changed_since(args.since), service_scripts())
    if args.only:
        chosen = {i for i in chosen if any(text in legs[i][0] for text in args.only)}
    chosen = sorted(chosen)
    for line in why:
        print(f'sweep: {line}')
    print(f'sweep: {len(chosen)} of {len(legs)} legs, {args.jobs} worker(s)', flush=True)
    if args.list:
        for i in chosen:
            print(('serial   ' if legs[i][2] else 'parallel ') + ('+ ' if legs[i][3] else '') + legs[i][0])
        return 0
    compiler = Path(subprocess.check_output([sys.executable, str(ROOT / 'qos.py'), 'fprisc', '--print'], text=True).strip()).resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    sweep = Sweep(args.output.resolve(), compiler, args.jobs, args.timeout)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, sweep.cancel)
    try:
        known = {r['name']: r['seconds'] for r in json.loads(args.times.read_text())['legs']} if args.times else None
        sweep.run(legs, set(chosen), known, not args.no_retry)
        sweep.cancelled_early = sweep.cancelled.is_set()
    finally:
        sweep.cancel()
    done = sweep.results
    count = lambda status: sum(1 for r in done.values() if r['status'] == status)
    bad = len(done) - count('passed') - count('skipped')
    alone = sum(1 for r in done.values() if r['status'] == 'passed' and r.get('first') in ('failed', 'timeout'))
    print(f'SWEEP: {count("passed")} passed, {bad} failed, {count("skipped")} skipped (of {len(done)} legs run; '
          f'{len(legs) - len(done)} not run), {time.monotonic() - sweep.began:.0f} s')
    if alone:
        print(f'NOTE: {alone} leg(s) failed beside other legs and passed alone; they are counted as passed and listed below')
        for result in done.values():
            if result['status'] == 'passed' and result.get('first') in ('failed', 'timeout'):
                print(f'   passed alone: {result["name"]}')
    for result in sorted(done.values(), key=lambda r: -r['seconds'])[:10]:
        print(f'  {result["seconds"]:7.1f} s  {result["name"]}')
    for result in done.values():
        if result['status'] not in ('passed', 'skipped'):
            print(f'** {result["status"]}: {result["name"]}\n   {result["log"]}')
    return 1 if bad or sweep.cancelled_early else 0


if __name__ == '__main__':
    sys.exit(main())
