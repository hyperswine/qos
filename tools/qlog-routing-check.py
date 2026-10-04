#!/usr/bin/env python3
"""Routed Qlog partial-write recovery and real System.qa storage startup."""
from pathlib import Path
import subprocess
import os
import tempfile
ROOT = Path(__file__).resolve().parents[1]

def run(args, cwd=ROOT, stdin=None, timeout=180, env=None):
    p = subprocess.run(list(map(str, args)), cwd=cwd, input=stdin,
                       capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout}{p.stderr}'
    return p.stdout + p.stderr

def build(source, kernel, directory, harts, flags=''):
    run(['make', '-s', 'native', f'SYSTEM={source}', f'KERNEL={kernel}', f'BUILD={directory}',
         f'NATIVE_CFLAGS_EXTRA={flags}', f'HARTS={harts}'], cwd=ROOT / 'qos')

def boot(kernel, harts, modern, disk=None, keys=None):
    args = ['qemu-system-riscv64', '-machine', 'virt', '-smp', harts, '-m', '256M',
            '-nographic', '-bios', 'none', '-kernel', kernel]
    if disk:
        args += ['-drive', f'file={disk},if=none,format=raw,id=hd0', '-device', 'virtio-blk-device,drive=hd0']
    if modern:
        args += ['-global', 'virtio-mmio.force-legacy=false']
    return run(args, stdin=keys, timeout=30)

with tempfile.TemporaryDirectory(prefix='qos-qlog-routing-') as d:
    temp = Path(d)
    host, app = temp / 'host', temp / 'portable.qa'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}'], cwd=ROOT / 'qos')
    run(['make', '-s', 'qos-app', 'PROG=tests/blockportable.fpr', f'BUILD={temp}/portable', f'QA_OUT={app}'])
    for harts in (1, 2):
        out = run([host, '--yes', app], cwd=temp, env={'FPR_HARTS': str(harts), 'FPR_DISK': str(temp / f'portable-{harts}.disk')})
        assert 'blockportable: query=True config=True write=True read=routed HOLDS' in out, out
        print(f'Portable block routing: {harts} hart(s), readiness/page I/O/native-budget refusal HOLDS', flush=True)
    for harts in (1, 2):
        probe, system, stalled = [temp / f'{harts}-{name}' for name in ('qlog.elf', 'system.elf', 'stalled.elf')]
        build(ROOT / 'tests/qlogblock.fpr', probe, temp / f'probe-{harts}', harts, '-DQOS_BLK_TEST')
        build(ROOT / 'programs/system.fpr', system, temp / f'system-{harts}', harts)
        # Same directory preserves the real bootstrap's importer-relative pins.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fpr', prefix='.qlog-startup-', dir=ROOT / 'programs') as fixture:
            src = (ROOT / 'programs/system.fpr').read_text()
            src = src.replace('main : unsafe Unit .', 'blkTestStallNth : Int -> Int .\nmain : unsafe Unit .')
            src = src.replace('  store = case pages == 0', '  _ = blkTestStallNth 1;\n  store = case pages == 0')
            fixture.write(src); fixture.flush()
            build(fixture.name, stalled, temp / f'stalled-{harts}', harts, '-DQOS_BLK_TEST -DBLK_DEADLINE_TICKS=1000000ULL')
        for modern in (False, True):
            disk = temp / f'probe-{modern}-{harts}.disk'
            run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
            out = boot(probe, harts, modern, disk)
            assert ('qlogblock: before=True aborted=True partial=True stale=True alive=True recovered=True write=True '
                    'replay=beforenext verified=True lost=True fast=True HOLDS') in out, out
            print(f'Qlog route: virtio v{2 if modern else 1}, {harts} hart(s), partial append/restart/service death HOLDS', flush=True)
            disk = temp / f'boot-{modern}-{harts}.disk'
            run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
            for count in (1, 2):
                out = boot(system, harts, modern, disk, 'yyyyq')
                assert f'storage: disk online -- boot #{count} on this log' in out, out
                assert 'System.qa: startup app returned; halting.' in out, out
            print(f'System routing: virtio v{2 if modern else 1}, {harts} hart(s), two persistent boots HOLDS', flush=True)
            # The first metadata read fails before readiness publication.
            disk = temp / f'stalled-{modern}-{harts}.disk'
            run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
            out = boot(stalled, harts, modern, disk, 'yyyyq')
            assert 'system: storage startup failed: dead actor' in out and 'storage: offline' in out, out
            assert 'storage: disk online' not in out and 'System.qa: startup app returned; halting.' in out, out
            print(f'System routing: virtio v{2 if modern else 1}, {harts} hart(s), failed initialization stays offline HOLDS', flush=True)
        out = boot(system, harts, False, keys='yyyyq')
        assert 'storage: offline' in out and 'storage: disk online' not in out, out
        assert 'System.qa: startup app returned; halting.' in out, out
        print(f'System routing: {harts} hart(s), no-disk bootstrap HOLDS', flush=True)
