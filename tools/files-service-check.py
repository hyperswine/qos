#!/usr/bin/env python3
"""Two-boot Files.qa persistence, application grants and owner-death refusal."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='qos-files-service-') as temp:
    out = Path(temp)
    env = dict(os.environ, FPR_HARTS='1', FPR_PORT='0', FPR_DISK=str(out / 'disk'))
    env.setdefault('XDG_CACHE_HOME', str(out / 'cache'))
    def run(args):
        p = subprocess.run(list(map(str, args)), cwd=out if args[0] == ROOT / 'qos/qosp' else ROOT,
                           env=env, capture_output=True, text=True, timeout=240)
        assert p.returncode == 0, p.stdout + p.stderr
        return p.stdout + p.stderr
    archive = out / 'filessvc.qa'
    run(['make', '-s', 'qos-app', 'PROG=tests/filessvc.fpr', f'QA_OUT={archive}', f'BUILD={out / "build"}'])
    run(['make', '-s', '-C', 'qos', 'portable'])
    for size in (6, 12):
        log = run([ROOT / 'qos/qosp', '--yes', archive])
        assert 'filessvc: HOLDS' in log, log
        assert f'filessvc: replay lengths {size} {size}' in log, log
    print('filessvc: two boots, shared disk, prefix refusal, compact refusal and dead owner HOLDS')
