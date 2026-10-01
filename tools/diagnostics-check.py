#!/usr/bin/env python3
"""Check negative diagnostic anchors with isolated files and captured output."""
from pathlib import Path
import os, subprocess, tempfile
ROOT = Path(__file__).resolve().parents[1]
FPR = Path(os.environ.get('FPRISC_ROOT', ROOT.parent / 'fprisc'))
with tempfile.TemporaryDirectory(prefix='qos-diagnostics-') as d:
    tmp = Path(d)
    cases = [
        ('sig.fpr', '# pad\nhelper x = x + 1.\n\nbroken : Int -> Int .\nbroken n = strcat n "oops".\nmain = broken 3.\n', ':4: in broken:'),
        ('linear.fpr', 'main =\n  v = Vec.push 1 (Vec.new Unit);\n  _ = Vec.free v;\n  _ = Vec.free v;\n  "x".\n', ':2:3: in main: linear variable'),
        ('root.fpr', 'M = use "mod".\nmain = _ = M.leak (Vec.newAs "i"); "x".\n', None),
        ('repeated.fpr', 'broken n =\n  a = strcat n "one";\n  b = strcat a "two";\n  c = strcat b 3;\n  c.\nmain = broken "hi".\n', ':4:7: in broken: application of strcat'),
    ]
    (tmp / 'mod.fpr').write_text('leak v = (Vec.len v, Vec.len v).\n')
    for name, source, suffix in cases:
        src = tmp / name
        src.write_text(source)
        p = subprocess.run([str(FPR / 'fpr'), '--profile=qos-portable', '--prelude='+str(FPR / 'core/prelude.fpr'), str(src), str(tmp / (name+'.s'))], capture_output=True, text=True, timeout=120)
        expected = str(src)+suffix if suffix else str(tmp / 'mod.fpr')+':1:6: in leak@'
        assert p.returncode != 0 and expected in p.stdout+p.stderr, (name, p.returncode, expected, p.stdout, p.stderr)
print('Diagnostic anchors: signature, linear binder, imported module and repeated token PASS')
