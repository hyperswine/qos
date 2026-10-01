#!/usr/bin/env python3
"""Baseline checks that do not depend on a graphics display or GPU."""
import os, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FPRISC = Path(os.environ.get('FPRISC_ROOT', ROOT.parent / 'fprisc')).resolve()
ENV = {**os.environ, 'FPR_HOME': str(ROOT), 'FPR_PATH': str(FPRISC),
       'FPR_FOREIGN': str(ROOT / 'core/foreign.fpr')}
def run(args, expected=0, contains=None, cwd=ROOT):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=ENV,
                       capture_output=True, text=True, timeout=180)
    assert p.returncode == expected, f'{args}: exit {p.returncode}\n{p.stdout}{p.stderr}'
    if contains:
        assert contains in p.stdout + p.stderr, p.stdout + p.stderr
    return p
# Runtime failure probes need the same compiler ABI as the app just built.
run(['make', '-s', '-C', 'qos', 'portable'])
with tempfile.TemporaryDirectory(prefix='qos-compile-gate-') as temp:
    tmp = Path(temp)
    def check(src, expected=0, contains=None):
        return run([FPRISC / 'fpr', '--profile=qos-portable',
                    f'--prelude={FPRISC}/core/prelude.fpr', '--check-only',
                    src, tmp / 'checked.s'], expected, contains)
    for name in ('gl2d', 'mvuweb'):
        check(ROOT / 'tests' / (name + '.fpr'))
    # LiveView has explicit unsafe declarations, not a trust exception.
    # Removing the entry's marker must still refuse the imported server call.
    unsafe_caller = tmp / 'unmarked-liveview.fpr'
    source = (ROOT / 'tests/mvuweb.fpr').read_text()
    source = source.replace('use "../programs/mods/liveview"',
                            'use "' + str(ROOT / 'programs/mods/liveview') + '"')
    unsafe_caller.write_text(source.replace('main : unsafe String .\n', ''))
    check(unsafe_caller, 1, 'main is unsafe')
    print('gl2d + LiveView compile without graphics; unmarked LiveView caller refused: PASS')
    # Malformed dynamic lists must fail explicitly instead of falling through
    # an incomplete pattern; the packed path also tests a live linear buffer.
    for packed in (False, True):
        src = tmp / ('bad-packed.fpr' if packed else 'bad-dynamics.fpr')
        call = ('fb = S2.fbNew 4;\n  (fb2, n) = S2.dynsInto fb [bad] Nil;\n  _ = Vec.free fb2;' if packed
                else '_ = S2.dyns [bad] Nil;')
        src.write_text('unsafe program.\nS2 = use "' + str(ROOT / 'programs/mods/scene2d') + '".\n'
                       'bad = S2.Ent "quad" (0, 0, 0) 0 (1, 1, 1) (0, 0, 0, 0).\n'
                       'main =\n  ' + call + '\n  "unreachable".\n')
        run(['make', '-s', 'qos-app', f'PROG={src}'])
        label = 'dynsInto' if packed else 'dyns'
        run([ROOT / 'qos/qosp', '--yes', ROOT / 'app.qa'], 1,
            f'scene2d.{label}: expected Sl in dynamic slots', cwd=tmp)
    print('scene2d: invalid dynamic entries fail by name in both list and packed paths: PASS')
