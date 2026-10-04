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
                     'missing image: refused', 'missing baseline: refused'):
        assert expected in out, out
    print(f'MVU real plugin reload: {harts} hart(s), state/render/scoped gate/refusals/old closure PASS')
