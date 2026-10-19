#!/usr/bin/env python3
"""Concurrent kv requests of one app each get their own reply (portable).

tests/storerace.fpr runs 16 actors of one app, 14 replaying the store
(tag 3) and 2 sending a write too large to accept (refused with a reason),
100 times each, and counts the replies that are not their own request's.
Messages between its actors carry only Ints.  With the old shared static
reply buffer (g_sysout in qos/appside/entry.c and qos/native/proc_entry.c)
the portable leg saw hundreds of crossed replies per run on an 8-core
x86-64 host; each call now has its own buffer.

  portable: 8 harts, three runs, zero mismatches (without the fix: 289
            of 1600 on an 8-core x86-64 host).

Native gets the same per-call buffer (qos/native/proc_entry.c), but no
native leg here: under QEMU the crossing never showed reliably, and a
loaded host turns storage deadlines into false mismatches.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ)
ENV.setdefault('FPRISC_ROOT', str(ROOT.parent / 'fprisc'))


def run(args, cwd=ROOT, timeout=300, extra=None):
    p = subprocess.run(list(map(str, args)), cwd=cwd, env={**ENV, **(extra or {})},
                       capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout[-6000:]}{p.stderr[-6000:]}'
    return p.stdout + p.stderr


def portable(tmp):
    host, image = tmp / 'qosp', tmp / 'storerace.qa'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}'], cwd=ROOT / 'qos')
    run(['make', '-s', 'qos-app', 'PROG=tests/storerace.fpr', f'QA_OUT={image}', f'BUILD={tmp / "app"}'])
    work = tmp / 'work'
    work.mkdir()
    for attempt in range(3):
        out = run([host, '--yes', image], cwd=work, timeout=120, extra={'FPR_HARTS': '8', 'FPR_PORT': '0'})
        m = re.search(r'storerace: mismatches=(\d+) of (\d+)', out)
        assert m and m.group(1) == '0', out[-3000:]
        print(f'store-race portable run {attempt + 1}: 0 mismatched of {m.group(2)} concurrent replies', flush=True)


if __name__ == '__main__':
    only = sys.argv[1:] or ['portable']
    with tempfile.TemporaryDirectory(prefix='qos-store-race-') as name:
        for leg in only:
            tmp = Path(name) / leg
            tmp.mkdir()
            {'portable': portable}[leg](tmp)
    print('store-race: PASS')
