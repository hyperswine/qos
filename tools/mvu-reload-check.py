#!/usr/bin/env python3
"""Real QOS plugin reloads on one/four harts, including refusals and old code."""
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RESULT = ('livereload: v1: 20 22 | v2 (same actor, acc kept): 30 | bad: refused | '
          'still v2: 36 | acc=108 [mvu: 3 frames, 2 statics builds]')
for harts in ('1', '4'):
    p = subprocess.run(['./qos.py', 'run', 'tests/livereload.fpr', '--harts', harts],
                       cwd=ROOT, capture_output=True, text=True, timeout=180)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    for expected in (RESULT, 'registry: 3 old closure: 20',
                     'missing image: refused', 'missing baseline: refused',
                     'stale source: refused', 'wrong image: refused',
                     'mathbad: arity changed for an export',
                     'mathtypebad: checked type, contract or ABI changed for an export',
                     'mathcontractbad: checked type, contract or ABI changed for an export',
                     'mathboundbad: checked type, contract or ABI changed for an export',
                     'mathopaquebad: new export has no checked interface'):
        assert expected in out, out
    print(f'MVU real plugin reload: {harts} hart(s), state/render/scoped gate/refusals/old closure PASS')

    p = subprocess.run(['./qos.py', 'run', 'tests/moduleinterfaces.fpr', '--harts', harts],
                       cwd=ROOT, capture_output=True, text=True, timeout=180)
    out = p.stdout + p.stderr
    assert p.returncode == 0 and 'checked contracts: old=20 new=30 registry=4' in out, out
    print(f'Checked precondition/work contract and specialized patch preserved: {harts} hart(s) PASS')
