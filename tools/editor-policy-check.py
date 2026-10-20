#!/usr/bin/env python3
"""Live Editor policies, captured file grants and real child confinement."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('main_profile', ROOT / 'tools/main-profile.py')
main_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(main_profile)


TESTS = ('editorpolicy', 'editorpolicyprocess', 'appsession', 'appsessionmemory')


def check(out, names=TESTS):
    env = dict(os.environ, FPRISC_ROOT=str(main_profile.fprisc_root()),
               FPR_PORT='0', XDG_CACHE_HOME=str(out / 'cache'))

    def run(name, args, **extra):
        p = subprocess.run(list(map(str, args)), cwd=ROOT,
                           env=dict(env, **extra), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=240)
        log = p.stdout + p.stderr
        (out / (name + '.log')).write_text(log)
        assert p.returncode == 0, f'{name}: exit {p.returncode}\n{log}'
        return log

    host = out / 'qosp'
    run('host-build', ['make', '-s', '-C', ROOT / 'qos', 'portable', f'QOSP_OUT={host}'])
    for name in names:
        image = out / (name + '.qa')
        run(name + '-build', ['make', '-s', 'qos-app', f'PROG=tests/{name}.fpr',
                             f'BUILD={out / (name + "-build")}', f'QA_OUT={image}'])
        def execute(sock=None):
            for harts in (1, 4):
                overrides = dict(FPR_HARTS=str(harts), FPR_DISK=str(out / f'{name}-{harts}.disk'))
                if sock:
                    overrides['FPRD_SOCK'] = sock
                log = run(f'{name}-{harts}', [host, '--yes', image], **overrides)
                assert name + ': HOLDS' in log and 'PANIC' not in log, log
                print(f'{name}: {harts} worker(s) HOLDS', flush=True)
        if name == 'editorpolicyprocess':
            with main_profile.compiler(out) as sock:
                execute(sock)
        else:
            execute()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--tests', nargs='+', choices=TESTS, default=TESTS)
    args = parser.parse_args()
    if args.output:
        out = args.output.resolve()
        out.mkdir(parents=True, exist_ok=True)
        check(out, args.tests)
    else:
        with tempfile.TemporaryDirectory(prefix='qos-editor-policy-') as directory:
            check(Path(directory), args.tests)
