#!/usr/bin/env python3
"""Portable storage deadlines, late replies and service resource admission."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
def run(command, cwd, env):
    p = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=240)
    assert p.returncode == 0, p.stdout+p.stderr
    return p.stdout+p.stderr
with tempfile.TemporaryDirectory(prefix='qos-storage-reliability-') as tmp:
    out = Path(tmp)
    env = dict(os.environ, FPR_PORT='0', XDG_CACHE_HOME=str(out/'cache'))
    host = out/'qosp'
    run(['make', '-s', '-C', 'qos', 'portable', f'QOSP_OUT={host}',
         'FPRBUILD_EXTRA=--cflag -DQOS_BLK_TEST'], ROOT, env)
    for name in ('storagedeadlines', 'storagebudgets', 'storerpc', 'qsysfail'):
        app = out/(name+'.qa')
        run(['make', '-s', 'qos-app', f'PROG=tests/{name}.fpr',
             f'QA_OUT={app}', f'BUILD={out/name}'], ROOT, env)
        for harts in (1, 4):
            values = dict(env, FPR_HARTS=str(harts), FPR_DISK=str(out/f'{name}-{harts}.disk'))
            if name == 'storagebudgets': values['QOS_BLK_TEST_DELAY_US'] = '100000'
            log = run([host, '--yes', app], out, values)
            assert name+':' in log and 'HOLDS' in log and 'FAILED' not in log, log
            print(f'{name}: {harts} worker(s) HOLDS', flush=True)
