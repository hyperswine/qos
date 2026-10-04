#!/usr/bin/env python3
"""Native ownership: late completion, reclaim cancellation and stale claim ABA."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER = Path(os.environ.get('FPRISC_ROOT') or ((ROOT / 'fprisc.path').read_text().strip() if (ROOT / 'fprisc.path').exists() else ROOT.parent / 'fprisc'))

def run(args, cwd=ROOT, timeout=180):
    p = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout}{p.stderr}'
    return p.stdout + p.stderr

def build(name, kernel, directory, harts, hal=None):
    run(['make', '-s', 'native', f'SYSTEM={ROOT}/tests/{name}.fpr',
         f'KERNEL={kernel}', f'BUILD={directory}', f'HARTS={harts}',
         'NATIVE_CFLAGS_EXTRA=-DQOS_BLK_TEST', *([f'HAL={hal}'] if hal else [])], cwd=ROOT / 'qos')

def boot(kernel, disk, harts, modern):
    args = ['qemu-system-riscv64', '-machine', 'virt', '-smp', harts, '-m', '256M',
            '-nographic', '-bios', 'none', '-kernel', kernel,
            '-drive', f'file={disk},if=none,format=raw,id=hd0', '-device', 'virtio-blk-device,drive=hd0']
    if modern:
        args += ['-global', 'virtio-mmio.force-legacy=false']
    return run(args, timeout=20)

with tempfile.TemporaryDirectory(prefix='qos-block-ownership-') as d:
    temp = Path(d)
    for bits in (32, 64):
        obj = temp / f'blk-{bits}.o'
        run(['riscv64-unknown-elf-gcc', f'-march=rv{bits}imafdc_zicsr',
             '-mabi=ilp32' if bits == 32 else '-mabi=lp64', '-mcmodel=medany',
             '-ffreestanding', '-O2', f'-I{COMPILER}/runtime', f'-I{COMPILER}/machine/virt',
             '-c', ROOT / 'hal/virt/blk.c', '-o', obj])
        symbols = run(['riscv64-unknown-elf-nm', obj])
        assert 'blkTest' not in symbols, symbols
        if bits == 32:
            assert 'qos_blk_' not in symbols and '__atomic_' not in symbols, symbols
        else:
            assert 'qos_blk_ownership' in symbols and 'qos_blk_claim_step' in symbols, symbols
        print(f'RV{bits} production object: expected policy ABI, no test hooks HOLDS', flush=True)
    for name in ('diskreclaimcancel', 'diskclaimrace'):
        for harts in (1, 2):
            kernel = temp / f'{name}-{harts}.elf'
            build(name, kernel, temp / f'{name}-{harts}', harts)
            for modern in (False, True):
                disk = temp / f'{name}-{harts}-{modern}.disk'
                run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
                out = boot(kernel, disk, harts, modern)
                assert f'{name}:' in out and 'HOLDS' in out and 'FAILED' not in out and 'PANIC' not in out, out
                if name == 'diskreclaimcancel':
                    assert '[blk] the device stalled on an abandoned request; reset' not in out, out
                print(f'{name}: virtio v{2 if modern else 1}, {harts} hart(s) HOLDS', flush=True)
    # Prove the race fixture rejects the old observation-before-CAS behavior.
    # Only a temporary raw policy copy differs; the production tree is intact.
    badhal = temp / 'unsafe-hal'
    shutil.copytree(ROOT / 'hal', badhal)
    policy = badhal / 'virt/blockpolicy.fpr'
    src = policy.read_text()
    old = 'claimStep 3 completed resetDue = if completed then 1 else 0.'
    assert src.count(old) == 1
    policy.write_text(src.replace(old, 'claimStep 3 completed resetDue = 1.'))
    kernel = temp / 'stale-policy.elf'
    build('diskclaimrace', kernel, temp / 'stale-policy', 2, badhal)
    disk = temp / 'stale-policy.disk'
    run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
    out = boot(kernel, disk, 2, True)
    assert 'diskclaimrace:' in out and 'FAILED' in out and 'HOLDS' not in out, out
    print('Stale completion policy mutation: race fixture rejects unsafe release HOLDS', flush=True)
