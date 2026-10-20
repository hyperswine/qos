#!/usr/bin/env python3
"""Linear ownership, live app/file policy, session transitions and memory parity."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FPRISC = Path(os.environ.get('FPRISC_ROOT', ROOT.parent / 'fprisc')).resolve()


def check(out):
    env = dict(os.environ, FPR_HOME=str(ROOT), FPR_PATH=str(FPRISC),
               FPR_FOREIGN=str(ROOT / 'core/foreign.fpr'), FPR_PORT='0',
               XDG_CACHE_HOME=str(out / 'cache'))

    def run(name, args, expected=0, **extra):
        result = subprocess.run(list(map(str, args)), cwd=out,
                                env=dict(env, **extra), capture_output=True,
                                text=True, timeout=240)
        log = result.stdout + result.stderr
        (out / (name + '.log')).write_text(log)
        assert result.returncode == expected, f'{name}: exit {result.returncode}\n{log}'
        return log

    prefix = f'unsafe program.\nES = use "{ROOT}/programs/mods/endpointstate".\n'
    refusals = {
        'duplicate': 'main = s = ES.acquired (1, 2); _ = ES.ended s; ES.ended s.',
        'discard': 'main = s = ES.acquired (1, 2); 42.',
        'discard-after-inspection': 'main = (snapshot, _) = ES.inspect (ES.acquired (1, 2)); snapshot.held.',
        'reuse-after-inspection': 'main = s = ES.acquired (1, 2); (snapshot, next) = ES.inspect s; _ = ES.ended s; ES.ended next.',
        'duplicate-generic': 'dup x = (x, x). main = (a, b) = dup (ES.acquired (1, 2)); _ = ES.ended a; ES.ended b.',
        'discard-cleanup-owner': 'main = (result, _) = ES.cleanup (myself 0) (ES.acquired (1, 2)); result.',
    }
    for name, body in refusals.items():
        source = out / (name + '.fpr')
        source.write_text(prefix + body + '\n')
        log = run(name, [FPRISC / 'fpr', '--profile=qos-portable',
                        f'--prelude={FPRISC}/core/prelude.fpr', '--check-only',
                        source, out / (name + '.s')], expected=1)
        assert 'linear' in log.lower() or 'owned' in log.lower(), log
        print(f'endpoint state: {name} refused', flush=True)

    host = out / 'qosp'
    run('host-build', ['make', '-s', '-C', ROOT / 'qos', 'portable', f'QOSP_OUT={host}'])
    for name in ('appjobs', 'appsession', 'appsessionmemory', 'filepolicy', 'apppolicy'):
        image = out / (name + '.qa')
        run(name + '-build', ['make', '-s', '-C', ROOT, 'qos-app',
                             f'PROG=tests/{name}.fpr', f'BUILD={out / (name + "-build")}',
                             f'QA_OUT={image}'])
        for harts in (1, 4):
            log = run(f'{name}-{harts}', [host, '--yes', image], FPR_HARTS=str(harts),
                      FPR_DISK=str(out / f'{name}-{harts}.disk'))
            assert name + ': HOLDS' in log and 'PANIC' not in log, log
            print(f'{name}: {harts} worker(s) HOLDS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        out = args.output.resolve()
        out.mkdir(parents=True, exist_ok=True)
        check(out)
    else:
        with tempfile.TemporaryDirectory(prefix='qos-endpoint-state-') as temp:
            check(Path(temp))
