#!/usr/bin/env python3
"""Check endpoint and log-adapter memory on one and four workers."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT / '.qos/ep-memory')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, XDG_CACHE_HOME=str(out / 'cache'))

    def run(argv, label, extra=None):
        p = subprocess.run(list(map(str, argv)), cwd=ROOT,
                           env={**env, **(extra or {})}, capture_output=True,
                           text=True, timeout=300)
        text = p.stdout + p.stderr
        (out / (label + '.log')).write_text(text)
        if p.returncode:
            raise RuntimeError(f'{label}: exit {p.returncode}\n{text[-4000:]}')
        return text

    host = out / 'qosp'
    run(['make', '-s', '-C', 'qos', 'portable', f'QOSP_OUT={host}'], 'host-build')
    for fixture in ('epmemory', 'logcapmemory'):
        archive = out / f'{fixture}.qa'
        run(['make', '-s', 'qos-app', f'PROG=tests/{fixture}.fpr',
             f'QA_OUT={archive}', f'BUILD={out / (fixture + "-build")}'],
            fixture + '-build')
        for harts in (1, 4):
            text = run([host, '--yes', archive], f'{fixture}-h{harts}',
                       {'FPR_HARTS': str(harts), 'FPR_PORT': '0',
                        'QOSP_ARENA_MB': '128'})
            assert f'{fixture}: HOLDS' in text and 'PANIC' not in text, text
            print(f'{fixture}: {harts} workers, 20000 cycles PASS', flush=True)


if __name__ == '__main__':
    main()
