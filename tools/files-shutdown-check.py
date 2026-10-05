#!/usr/bin/env python3
"""Files quiesce then block drain, refusal, idempotence and persisted content."""
from pathlib import Path
import os
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
def run(args, cwd=ROOT, env=None, timeout=240):
    p = subprocess.run(list(map(str, args)), cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.stdout}{p.stderr}'
    return p.stdout + p.stderr
with tempfile.TemporaryDirectory(prefix='qos-files-shutdown-') as d:
    temp = Path(d)
    host, app = temp / 'qosp', temp / 'shutdown.qa'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}'], cwd=ROOT / 'qos')
    run(['make', '-s', 'qos-app', 'PROG=tests/filesshutdown.fpr', f'QA_OUT={app}', f'BUILD={temp}/portable'])
    for harts in (1, 2):
        out = run([host, '--yes', app], cwd=temp, env={'FPR_HARTS': str(harts), 'FPR_DISK': str(temp / f'portable-{harts}.disk')})
        assert 'latched=True HOLDS' in out and 'FAILED' not in out, out
        print(f'Files shutdown: Portable, {harts} hart(s) HOLDS', flush=True)
        kernel = temp / f'shutdown-{harts}.elf'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fpr', prefix='.shutdown-', dir=ROOT / 'tests') as fixture:
            source = (ROOT / 'tests/filesshutdown.fpr').read_text()
            source = source.replace('B = use', 'Native = use "../std/block".\nB = use', 1)
            source = source.replace('B.serve me (device "blk")', 'Native.serveOn hart me (device "blk")')
            source = source.replace('B.serve 999 (device "blk")', 'Native.serveOn hart 999 (device "blk")')
            fixture.write(source); fixture.flush()
            run(['make', '-s', 'native', f'SYSTEM={fixture.name}', f'KERNEL={kernel}', f'BUILD={temp}/native-{harts}', f'HARTS={harts}'], cwd=ROOT / 'qos')
        active = temp / f'active-{harts}.elf'
        run(['make', '-s', 'native', f'SYSTEM={ROOT}/tests/filesshutdownactive.fpr', f'KERNEL={active}', f'BUILD={temp}/active-{harts}', f'HARTS={harts}', 'NATIVE_CFLAGS_EXTRA=-DQOS_BLK_TEST'], cwd=ROOT / 'qos')
        for modern in (False, True):
            disk = temp / f'disk-{harts}-{modern}'
            run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
            args = ['qemu-system-riscv64', '-machine', 'virt', '-smp', harts, '-m', '256M', '-nographic', '-bios', 'none', '-kernel', kernel,
                    '-drive', f'file={disk},if=none,format=raw,id=hd0', '-device', 'virtio-blk-device,drive=hd0']
            if modern: args += ['-global', 'virtio-mmio.force-legacy=false']
            out = run(args, timeout=30)
            assert 'latched=True HOLDS' in out and 'FAILED' not in out, out
            print(f'Files shutdown: virtio v{2 if modern else 1}, {harts} hart(s) HOLDS', flush=True)

            activeDisk = temp / f'active-disk-{harts}-{modern}'
            run(['python3', ROOT / 'tools/mkdisk.py', activeDisk, '8'])
            args[args.index(kernel)] = active
            args[args.index(f'file={disk},if=none,format=raw,id=hd0')] = f'file={activeDisk},if=none,format=raw,id=hd0'
            out = run(args, timeout=30)
            assert 'reserved=True HOLDS' in out and 'FAILED' not in out, out
            print(f'Files shutdown behind failed I/O: virtio v{2 if modern else 1}, {harts} hart(s), DMA remains reserved HOLDS', flush=True)
