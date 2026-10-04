#!/usr/bin/env python3
"""Native versioned block budgets and correlated service failure boundaries."""
import shutil
import subprocess
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def run(args, cwd=ROOT, timeout=180):
    p = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout}{p.stderr}'
    return p.stdout + p.stderr

if not shutil.which('qemu-system-riscv64') or not shutil.which('riscv64-unknown-elf-gcc'):
    raise SystemExit('Native block service: prerequisites missing (RV64 compiler and QEMU required)')
with tempfile.TemporaryDirectory(prefix='qos-block-service-') as d:
    temp = Path(d)
    kernels = {}
    for harts in (1, 2):
        kernels[harts] = temp / f'service-{harts}.elf'
        run(['make', '-s', 'native', f'SYSTEM={ROOT}/tests/blockservice.fpr', f'KERNEL={kernels[harts]}', f'BUILD={temp}/build-{harts}',
             f'HARTS={harts}', 'NATIVE_CFLAGS_EXTRA=-DQOS_BLK_TEST -DBLK_DEADLINE_TICKS=3000000ULL'], cwd=ROOT / 'qos')
    for modern in (False, True):
        for harts in (1, 2):
            disk = temp / f'service-{modern}-{harts}.disk'
            run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
            args = ['qemu-system-riscv64', '-machine', 'virt', '-smp', harts, '-m', '256M', '-nographic',
                    '-bios', 'none', '-kernel', kernels[harts], '-drive', f'file={disk},if=none,format=raw,id=hd0',
                    '-device', 'virtio-blk-device,drive=hd0']
            if modern:
                args += ['-global', 'virtio-mmio.force-legacy=false']
            out = run(args, timeout=30)
            want = ('blockservice: invalid=True stale=True unchanged=True auth=True range=True size=True '
                    'busy=True reserved=True timeout=True timed=True alive=True overload=True cancelled=True offline=True '
                    'refused=True fast=True liveOffline=True offlineConfig=True after=before HOLDS')
            assert want in out, out
            print(f'Native block service: virtio v{2 if modern else 1}, {harts} hart(s), budgets/refusal/recovery HOLDS', flush=True)
