#!/usr/bin/env python3
"""Hosted timer lifecycle, ownership refusals and enforced arithmetic bounds."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FPRISC = Path(os.environ.get('FPRISC_ROOT', ROOT.parent / 'fprisc')).resolve()


def check(out):
    env = dict(os.environ, FPRISC_ROOT=str(FPRISC), FPR_HOME=str(ROOT),
               FPR_PATH=str(FPRISC), FPR_FOREIGN=str(ROOT / 'core/foreign.fpr'),
               FPR_PORT='0', XDG_CACHE_HOME=str(out / 'cache'))
    evidence = []

    def run(name, args, expected=0, contains=(), **extra):
        process = subprocess.Popen(list(map(str, args)), cwd=out,
                                   env=dict(env, **extra), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, start_new_session=True)
        try:
            log, _ = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            log, _ = process.communicate()
            (out / (name + '.log')).write_text(log)
            raise
        (out / (name + '.log')).write_text(log)
        exits = expected if isinstance(expected, tuple) else (expected,)
        assert process.returncode in exits, f'{name}: exit {process.returncode}\n{log}'
        for text in contains:
            assert text in log, f'{name}: missing {text!r}\n{log}'
        evidence.append({'check': name, 'exit': process.returncode})
        return log

    compiler = [FPRISC / 'fpr', '--target=qa64',
                f'--prelude={FPRISC}/core/prelude.fpr', '--check-only']
    costs = run('arithmetic-bounds', compiler + ['--lib', '--cost', ROOT / 'std/hostedtime.fpr', out / 'bounds.s'])
    assert 'microseconds' in costs and 'slice' in costs and costs.count('PROVEN') == 4, costs

    prefix = ('unsafe program.\nH = use "std/hosted".\n'
              'T = use "std/hostedtimers".\nTime = use "std/hostedtime".\n')
    refusals = {
        'duplicate-pool': ('main = p = T.open 1; _ = T.close p; T.close p.', 'linear'),
        'discard-pool': ('main = p = T.open 1; 42.', 'linear'),
        'discard-returned-owner': ('main = p = T.open 1; (n, _) = T.usage p; n.', 'linear'),
        'reuse-before-inspection': ('main = p = T.open 1; (n, next) = T.usage p; _ = T.close p; T.close next.', 'linear'),
        'duplicate-through-generic': ('dup x = (x, x).\nmain = (a, b) = dup (T.open 1); _ = T.close a; T.close b.', 'owned'),
        'project-away-owner': ('main = m = {n = 1, pool = T.open 1}; m.n.', 'linear'),
    }
    contracts = {
        'zero-period': ('main = H.every 0 1.', 'precondition'),
        'negative-period': ('main = H.every (0 - 1) 1.', 'precondition'),
        'negative-delay': ('main = H.after (0 - 1) 1.', 'precondition'),
        'unsafe-conversion': ('main = Time.microseconds 1001.', 'precondition'),
        'zero-owner-quantum': ('main = Time.slice 0 1.', 'precondition'),
        'oversized-owner-quantum': ('main = Time.slice 1001 1.', 'precondition'),
        'zero-remaining-time': ('main = Time.slice 1 0.', 'precondition'),
        'zero-capacity': ('main = T.close (T.open 0).', 'precondition'),
        'oversized-capacity': ('main = T.close (T.open 1025).', 'precondition'),
    }
    for name, (body, diagnostic) in refusals.items():
        source = out / (name + '.fpr')
        source.write_text(prefix + body + '\n')
        log = run(name, compiler + [source, out / (name + '.s')], expected=1)
        assert diagnostic in log.lower(), f'{name}: wrong refusal\n{log}'

    # Check that the new claims remain enforced, rather than accepting any
    # diagnostic/report as proof. The actual arithmetic needs one operation.
    over = out / 'insufficient-work.fpr'
    over.write_text((ROOT / 'std/hostedtime.fpr').read_text().replace(
        'work microseconds <= 1', 'work microseconds <= 0'))
    run('insufficient-work', compiler + ['--lib', over, out / 'over.s'],
        expected=1, contains=('COST: ERRORS', 'OVER'))
    unsafe = out / 'unsafe-callback.fpr'
    unsafe.write_text('''H = use "std/hosted".
bad n = bad (n + 1).
update event model = (bad model, Nil).
view size model = Nil.
subs model = Nil.
app = {init = 0, update = update, view = view, subs = subs}.
main = H.host (myself 0) (H.Start (myself 0) 40 10) app.
''')
    run('unsafe-callback', compiler + [unsafe, out / 'unsafe.s'], expected=1,
        contains=('SAFETY: the safe/unsafe line', 'bad is unsafe (recursive)'))

    host = out / 'qosp'
    run('host-build', ['make', '-s', '-C', ROOT / 'qos', 'portable', f'QOSP_OUT={host}'])
    # Imported refinements can be runtime checked by this compiler. Execute
    # each bad call and require named contract blame, rather than confusing
    # a successful check-only compilation with enforcement.
    for name, (body, diagnostic) in contracts.items():
        source = out / (name + '.fpr')
        source.write_text(prefix + body + '\n')
        log = run(name + '-check', compiler + [source, out / (name + '.s')], expected=(0, 1))
        if evidence[-1]['exit'] == 1:
            assert diagnostic in log.lower(), f'{name}: wrong refusal\n{log}'
        else:
            image = out / (name + '.qa')
            run(name + '-build', ['make', '-s', '-C', ROOT, 'qos-app',
                                 f'PROG={source}', f'QA_OUT={image}', f'BUILD={out / (name + "-build")}'])
            log = run(name + '-guard', [host, '--yes', image], expected=1,
                      FPR_HARTS='1', FPR_DISK=str(out / (name + '.disk')))
            assert diagnostic in log.lower(), f'{name}: wrong failure\n{log}'
    for name in ('hostedtimers', 'appsession'):
        image = out / (name + '.qa')
        run(name + '-build', ['make', '-s', '-C', ROOT, 'qos-app',
                             f'PROG=tests/{name}.fpr', f'QA_OUT={image}',
                             f'BUILD={out / (name + "-build")}'])
        for harts in (1, 4):
            run(f'{name}-{harts}', [host, '--yes', image],
                contains=(name + ': HOLDS',), FPR_HARTS=str(harts),
                FPR_HEAP_MB='128', QOSP_ARENA_MB='128',
                FPR_DISK=str(out / f'{name}-{harts}.disk'))
            print(f'{name}: {harts} worker(s) HOLDS', flush=True)
    (out / 'results.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(f'hosted timers: {len(refusals)} ownership refusals, {len(contracts)} contract guards, '
          'enforced work/allocation bounds and lifecycle integration HOLDS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Keep build logs and results in this directory')
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        check(args.output.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='qos-hosted-timers-') as tmp:
            check(Path(tmp))
