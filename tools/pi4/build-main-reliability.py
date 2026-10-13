#!/usr/bin/env python3
"""Build a matching Pi Main bundle and seed two hidden reload fixtures.

Run inside the ARM64 Linux SDK VM. No installed image or disk is modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tomllib
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from mkdisk import chunk_hash, PG
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--output', required=True, type=Path)
ap.add_argument('--cc', required=True)
a = ap.parse_args()
if platform.system() != 'Linux' or platform.machine() != 'aarch64':
    ap.error('requires ARM64 Linux')
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
fprisc = Path(os.environ.get('FPRISC_ROOT', ROOT.parent/'fprisc'))
def run(*args, cwd=ROOT):
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)
run('make', '-s', 'fpr', cwd=fprisc)
for name in ('inbox', 'inboxshared', 'inboxownership'):
    args = [fprisc/'fpr', 'build', fprisc/f'tests/base/{name}.fpr',
            '--harts', '4', '--cc', a.cc, '-o', out/(name+'-base')]
    if name == 'inboxownership': args += ['--with', fprisc/'tests/base/inbox_probe.c']
    run(*args, cwd=fprisc)
profile = tomllib.loads((ROOT/'profiles/Main.toml').read_text())
archives = []
for source in [*profile['apps'], 'tests/mathv1.fpr', 'tests/mathv2.fpr']:
    name = Path(source).stem
    archive = out/(name+'.qa')
    run('make', '-s', 'plugin-qa-a64', f'PROG={source}', f'PLUG_OUT={archive}', f'BUILD={out/("build-"+name)}')
    archives.append(archive)
run('make', '-s', 'qos-app-a64', 'PROG=tests/mainreliability.fpr', f'QA_OUT={out/"main.qa"}', f'BUILD={out/"build-main"}')
for name in ('storagedeadlines', 'storagebudgets', 'blockmemory', 'filesshutdown', 'filessvc'):
    run('make', '-s', 'qos-app-a64', f'PROG=tests/{name}.fpr', f'QA_OUT={out/(name+".qa")}', f'BUILD={out/("build-"+name)}')
run('make', '-s', '-C', 'qos', 'portable-es', f'QOSP_ES_OUT={out/"qosp-es"}',
    f'FPRBUILD_EXTRA=--cc {a.cc} --cflag -g --cflag -DQOS_BLK_TEST --cflag -DQOS_STORE_TEST',
    'SND_FLAGS=-DQOSP_SND_ALSA', 'SND_LIBS=-lasound')
run(a.cc, '-O2', '-Wall', '-Wextra', ROOT/'tools/pi4/runner.c', '-o', out/'runner')
run('python3', ROOT/'tools/mkdisk.py', out/'Main.disk', 32, *archives[:len(profile['apps'])])
# These fixtures are records, not installed applications or extra shell tiles.
disk = bytearray((out/'Main.disk').read_bytes())
head = int(re.match(rb'QLOG (\d+) ', disk)[1])
for key, archive in zip(('soak/reload-a', 'soak/reload-b'), archives[-2:]):
    data = archive.read_bytes()
    pages = (len(data)+PG-1)//PG
    header = f'QREC {pages} {len(data)} {key} h{chunk_hash(data)}\n'.encode()
    disk[head*PG:head*PG+len(header)] = header
    disk[(head+1)*PG:(head+1)*PG+len(data)] = data
    head += 1+pages
pages = len(disk)//PG
data_end = pages-pages//8
assert head < data_end, 'reload seed exceeds DATA partition'
disk[:PG] = bytes(PG)
header = f'QLOG {head} v2 w0 c1 d{data_end} s{data_end} m0\n'.encode()
disk[:len(header)] = header
(out/'Main.disk').write_bytes(disk)
def tree(path):
    return {'head': subprocess.check_output(['git', '-C', path, 'rev-parse', 'HEAD'], text=True).strip(),
            'tracked_diff_sha256': hashlib.sha256(subprocess.check_output(['git', '-C', path, 'diff', 'HEAD'])).hexdigest()}
manifest = {'qos': tree(ROOT), 'fprisc': tree(fprisc), 'files':
    {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()},
    'cc': subprocess.check_output([a.cc, '--version'], text=True).splitlines()[0],
    'scope': 'diagnostic Main entry; two reload generations; isolated SD-backed disk'}
(out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
