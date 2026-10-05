#!/usr/bin/env python3
"""Block cancellation/drain and granted namespace pages, Native and Portable."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def run(args, cwd=ROOT, env=None, timeout=180):
    p = subprocess.run(list(map(str, args)), cwd=cwd, env={**os.environ, **(env or {})},
                       capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout}{p.stderr}'
    return p.stdout + p.stderr

def build(source, kernel, directory, harts, flags=''):
    run(['make', '-s', 'native', f'SYSTEM={source}', f'KERNEL={kernel}', f'BUILD={directory}',
         f'HARTS={harts}', f'NATIVE_CFLAGS_EXTRA={flags}'], cwd=ROOT / 'qos')

def boot(kernel, disk, harts, modern):
    args = ['qemu-system-riscv64', '-machine', 'virt', '-smp', harts, '-m', '256M',
            '-nographic', '-bios', 'none', '-kernel', kernel, '-drive', f'file={disk},if=none,format=raw,id=hd0',
            '-device', 'virtio-blk-device,drive=hd0']
    if modern:
        args += ['-global', 'virtio-mmio.force-legacy=false']
    return run(args, timeout=30)

def holds(out, name):
    assert f'{name}:' in out and 'HOLDS' in out and 'FAILED' not in out and 'PANIC' not in out, out

with tempfile.TemporaryDirectory(prefix='qos-block-lifecycle-') as d:
    temp = Path(d)
    host = temp / 'host'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}', 'FPRBUILD_EXTRA=--cflag -DQOS_BLK_TEST'], cwd=ROOT / 'qos')
    for name in ('blocknamespace', 'blocklifecyclep'):
        archive = temp / f'{name}.qa'
        run(['make', '-s', 'qos-app', f'PROG=tests/{name}.fpr', f'BUILD={temp}/{name}', f'QA_OUT={archive}'])
        for harts in (1, 2):
            env = {'FPR_HARTS': str(harts), 'FPR_DISK': str(temp / f'{name}-{harts}.disk')}
            if name == 'blocklifecyclep':
                env.update(QOS_BLK_TEST_DELAY_US='800000', QOS_BLK_TEST_DELAY_READS='1', QOS_BLK_DEADLINE_MS='300')
            out = run([host, '--yes', archive], cwd=temp, env=env, timeout=30)
            holds(out, name)
            print(f'Portable {name}: {harts} hart(s) HOLDS', flush=True)
    for harts in (1, 2):
        lifecycle = temp / f'lifecycle-{harts}.elf'
        build(ROOT / 'tests/blocklifecycle.fpr', lifecycle, temp / f'lifecycle-{harts}', harts, '-DQOS_BLK_TEST')
        endpoint = temp / f'namespace-{harts}.elf'
        # Exercise native budgets through the same namespace adapter. Keep
        # the source in tests/ so all importer-relative module paths remain valid.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fpr', prefix='.block-namespace-', dir=ROOT / 'tests') as fixture:
            src = (ROOT / 'tests/blocknamespace.fpr').read_text()
            src = 'Native = use "../std/block".\n' + src.replace('block = B.serve me', 'block = Native.serve me')
            src = src.replace('budget = err "block: native budgets unsupported"', 'budget = ok')
            fixture.write(src); fixture.flush()
            build(fixture.name, endpoint, temp / f'namespace-{harts}', harts)
        for modern in (False, True):
            for name, kernel in (('blocklifecycle', lifecycle), ('blocknamespace', endpoint)):
                disk = temp / f'{name}-{harts}-{modern}.disk'
                run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
                out = boot(kernel, disk, harts, modern)
                holds(out, name)
                print(f'Native {name}: virtio v{2 if modern else 1}, {harts} hart(s) HOLDS', flush=True)
