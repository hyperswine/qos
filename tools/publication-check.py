#!/usr/bin/env python3
"""QOS publication failures, real watcher swaps and two boots on one/four harts."""
import subprocess, tempfile, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RESULT='publication: old=20 new=30 rows=2 owned=stopped PASS'
def run(args):
    p=subprocess.run(['./qos.py','run','tests/qpublication.fpr',*args],cwd=ROOT,
                     capture_output=True,text=True,timeout=180)
    out=p.stdout+p.stderr
    assert p.returncode==0 and RESULT in out,out
    return out
with tempfile.TemporaryDirectory(prefix='qos-publication-') as directory:
    for harts in ('1','4'):
        out=run(['--harts',harts])
        for label in ('image','journal','read','malformed','collision','stale','delimiter','invalid archive'):
            assert f'{label}: refused' in out,out
        disk=Path(directory)/f'boot-{harts}.img'
        shutil.copyfile(ROOT/'.qos/build/plugdisk-qpublication.img',disk)
        out=run(['--harts',harts,'--no-plugins','--disk',str(disk)])
        assert 'image: refused' not in out,'second boot reseeded publication'
        print(f'QOS publication: {harts} hart(s), two boots, failures, immutable retry, owned MVU watcher PASS')
