#!/usr/bin/env python3
"""App ids are one safe path component, on both targets.

Portable: a real qosp and .qa whose manifest id is the review's repro
"../escaped" (it wrote escaped.kv OUTSIDE qos-store/) and other bad ids is
refused by name before the app runs, and nothing is written anywhere; good
ids (up to 64 bytes) still get their own qos-store/<id>.kv.  Native: the
manifest parser refuses the same archive, the kernel refuses to place a
process under a bad or over-long bound id, and 64-byte ids sharing a
63-byte prefix keep separate stores (tests/appidnative.fpr, under QEMU).
(qos/app_id.h, programs/mods/manifest.fpr validId)
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ)
ENV.setdefault('FPRISC_ROOT', str(ROOT.parent / 'fprisc'))
BAD = {
    '../escaped': "may not start with '.' or '-'",
    'a/b': 'may use only A-Z a-z 0-9 _ - . and no ".."',
    'a..b': 'may use only A-Z a-z 0-9 _ - . and no ".."',
    '..': "may not start with '.' or '-'",
    '.hidden': "may not start with '.' or '-'",
    '-dash': "may not start with '.' or '-'",
    'sp ace': 'may use only A-Z a-z 0-9 _ - . and no ".."',
    'x' * 65: 'is longer than 64 bytes',
    '': 'id is missing',
}
GOOD = ['ok', 'Com.Example-app_1', 'y' * 64]


def run(args, cwd=ROOT, timeout=300, extra=None, check=True):
    p = subprocess.run(list(map(str, args)), cwd=cwd, env={**ENV, **(extra or {})},
                       capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if check:
        assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout[-6000:]}{p.stderr[-6000:]}'
    return p


def manifest(path, app_id):
    path.write_text(f'name = "idprobe"\nid = "{app_id}"\nentry = "n/a"\nversion = "1"\n'
                    f'loadMode = "process"\nabi = "{ABI}"\n')
    return path


def portable(tmp):
    host, base = tmp / 'qosp', tmp / 'appidproc.qa'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}'], cwd=ROOT / 'qos')
    build = tmp / 'app'
    run(['make', '-s', 'qos-app', 'PROG=tests/appidproc.fpr', f'QA_OUT={base}', f'BUILD={build}'])
    global ABI
    ABI = next(l.split('"')[1] for l in (build / 'qosapp-gen.toml').read_text().splitlines() if l.startswith('abi'))
    for n, (app_id, why) in enumerate(BAD.items()):
        qa = tmp / f'bad{n}.qa'
        run(['python3', 'tools/mkqa.py', manifest(tmp / f'bad{n}.toml', app_id), build / 'qosapp.elf', '-o', qa,
             '--relocatable', '--check-moved', build / 'qosapp.moved.elf', '--delta', '0x10000000'])
        work = tmp / f'badrun{n}' / 'work'
        work.mkdir(parents=True)
        p = run([host, '--yes', qa], cwd=work, timeout=60, extra={'FPR_HARTS': '2', 'FPR_PORT': '0'}, check=False)
        text = p.stdout + p.stderr
        assert p.returncode != 0 and why in text and 'appidproc:' not in text, (app_id, p.returncode, text)
        left = [q for q in (tmp / f'badrun{n}').rglob('*') if q.is_file()]
        assert not left, (app_id, left)
    print(f'app-id portable: {len(BAD)} bad ids (incl. "../escaped") refused by name, nothing written: PASS', flush=True)
    for n, app_id in enumerate(GOOD):
        qa = tmp / f'good{n}.qa'
        run(['python3', 'tools/mkqa.py', manifest(tmp / f'good{n}.toml', app_id), build / 'qosapp.elf', '-o', qa,
             '--relocatable', '--check-moved', build / 'qosapp.moved.elf', '--delta', '0x10000000'])
        work = tmp / f'goodrun{n}'
        work.mkdir()
        text = run([host, '--yes', qa], cwd=work, timeout=60, extra={'FPR_HARTS': '2', 'FPR_PORT': '0'}).stdout
        assert 'appidproc: ok 1' in text, (app_id, text)
        assert [q.name for q in (work / 'qos-store').iterdir()] == [f'{app_id}.kv'], app_id
    print(f'app-id portable: good ids up to 64 bytes keep their own qos-store/<id>.kv: PASS', flush=True)


def native(tmp):
    if not all(shutil.which(x) for x in ('qemu-system-riscv64', 'riscv64-unknown-elf-gcc')):
        print('app-id native: SKIP (needs RV64 compiler and QEMU)')
        return
    archives = []
    for name, app_id in (('CkSlow', 'CkSlow'), ('CkBad', '../escaped')):
        mf = tmp / f'{name}.toml'
        mf.write_text(f'name = "{name}"\nid = "{app_id}"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n')
        qa = tmp / f'{name}.qa'
        run(['tools/build-process-app.sh', 'tests/appidproc.fpr', mf, qa])
        archives.append(qa)
    disk = tmp / 'disk'
    # mkdisk names a disk entry by the archive's file name
    run(['python3', 'tools/mkdisk.py', disk, '16', *archives])
    for harts in (1, 2):
        kernel = tmp / f'appidnative-{harts}.elf'
        run(['make', '-s', '-C', 'qos', 'native', f'SYSTEM={ROOT}/tests/appidnative.fpr',
             f'KERNEL={kernel}', f'BUILD={tmp}/native-{harts}', f'HARTS={harts}'])
        img = tmp / f'disk-{harts}'
        shutil.copy(disk, img)
        log = run(['qemu-system-riscv64', '-machine', 'virt', '-smp', str(harts), '-m', '256M',
                   '-nographic', '-bios', 'none', '-kernel', kernel,
                   '-drive', f'file={img},if=none,format=raw,id=hd0',
                   '-device', 'virtio-blk-device,drive=hd0'], timeout=120).stdout
        assert 'PANIC' not in log and 'appidnative:' in log and ' HOLDS' in log, log[-4000:]
        print(f'app-id native ({harts} hart(s)): parser and kernel refuse bad ids, 64-byte ids keep separate stores: PASS', flush=True)


ABI = ''
if __name__ == '__main__':
    only = sys.argv[1:] or ['portable', 'native']
    with tempfile.TemporaryDirectory(prefix='qos-app-id-') as name:
        for leg in only:
            {'portable': portable, 'native': native}[leg](Path(name))
