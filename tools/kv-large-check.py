#!/usr/bin/env python3
"""kv replays larger than the old 256 KiB reply buffer, on both targets.

The app (tests/kvlarge.fpr) grows its log to 200 KB, exactly 256 KiB and
300 KB, and reads every byte back.  Portable: a real qosp and .qa.  Native:
the same program as a relocatable process image under QEMU (1 and 2 harts),
where the kernel trampoline used to truncate the reply into an Ok.
(qos/store_abi.h; the host-level contract is in qos/tests-host/store-check.sh)
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
WANT = 'kvlarge: 200000:True 262144:True 300000:True'


def run(args, cwd=ROOT, timeout=300, extra=None):
    p = subprocess.run(list(map(str, args)), cwd=cwd, env={**ENV, **(extra or {})},
                       capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout[-6000:]}{p.stderr[-6000:]}'
    return p.stdout + p.stderr


def portable(tmp):
    host, image = tmp / 'qosp', tmp / 'kvlarge.qa'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}'], cwd=ROOT / 'qos')
    run(['make', '-s', 'qos-app', 'PROG=tests/kvlarge.fpr', f'QA_OUT={image}', f'BUILD={tmp / "app"}'])
    work = tmp / 'portable'
    work.mkdir()
    out = run([host, '--yes', image], cwd=work, timeout=60, extra={'FPR_HARTS': '2', 'FPR_PORT': '0'})
    assert WANT in out, out
    files = list((work / 'qos-store').glob('*.kv'))
    assert len(files) == 1, files
    print('kv-large portable: 200 KB, 256 KiB, 300 KB replays intact: PASS', flush=True)


def native(tmp):
    if not all(shutil.which(x) for x in ('qemu-system-riscv64', 'riscv64-unknown-elf-gcc')):
        print('kv-large native: SKIP (needs RV64 compiler and QEMU)')
        return
    manifest = tmp / 'CkSlow.toml'
    manifest.write_text('name = "CkSlow"\nid = "CkSlow"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n')
    qa = tmp / 'CkSlow.qa'
    run(['tools/build-process-app.sh', 'tests/kvlarge.fpr', manifest, qa])
    for harts in (1, 2):
        disk = tmp / f'disk-{harts}'
        run(['python3', 'tools/mkdisk.py', disk, '32', qa])
        kernel = tmp / f'kvlargenative-{harts}.elf'
        run(['make', '-s', '-C', 'qos', 'native', f'SYSTEM={ROOT}/tests/kvlargenative.fpr',
             f'KERNEL={kernel}', f'BUILD={tmp}/native-{harts}', f'HARTS={harts}'])
        log = run(['qemu-system-riscv64', '-machine', 'virt', '-smp', str(harts), '-m', '256M',
                   '-nographic', '-bios', 'none', '-kernel', kernel,
                   '-drive', f'file={disk},if=none,format=raw,id=hd0',
                   '-device', 'virtio-blk-device,drive=hd0'], timeout=120)
        assert 'PANIC' not in log and f'kvlargenative: [{WANT}] HOLDS' in log, log[-4000:]
        print(f'kv-large native ({harts} hart(s)): 200 KB, 256 KiB, 300 KB replays intact: PASS', flush=True)


if __name__ == '__main__':
    only = sys.argv[1:] or ['portable', 'native']
    with tempfile.TemporaryDirectory(prefix='qos-kv-large-') as name:
        for leg in only:
            {'portable': portable, 'native': native}[leg](Path(name))
