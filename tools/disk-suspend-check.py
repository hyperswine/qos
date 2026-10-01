#!/usr/bin/env python3
"""Real HAL disk wait: one hart makes progress; legacy synchronous path doesn't."""
import os, subprocess, tempfile, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def run(args, cwd=ROOT, env=None, timeout=300):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env={**os.environ, **(env or {})},
                       capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout}{p.stderr}'
    return p
with tempfile.TemporaryDirectory(prefix='qos-disk-wait-') as d:
    tmp = Path(d)
    exe = tmp / 'worker'
    run(['cc', '-O1', '-g', '-fsanitize=address', '-Wall', '-Wextra',
         ROOT/'tests/host/disk_async_check.c', '-lpthread', '-o', exe])
    print(run([exe], cwd=tmp, env={'FPR_DISK':str(tmp/'worker.disk')}).stdout.strip())
    host = tmp/'host'
    run(['make','-s','portable',f'QOSP_OUT={host}',
         'FPRBUILD_EXTRA=--cflag -DQOS_BLK_TEST'], cwd=ROOT/'qos')
    for sync in (True, False):
        # Separate directories make each compile-flag variant a fresh build.
        run(['make','-s','qos-app','PROG=tests/diskprogress.fpr',
             f'BUILD={tmp}/app-{sync}',
             f'QA_OUT={tmp}/progress.qa',
             'QOSCFLAGS_EXTRA=' + ('-DQOS_DISK_TEST_SYNC' if sync else '')])
        p=run([host,'--yes',tmp/'progress.qa'],cwd=tmp,
              env={'FPR_HARTS':'1','FPR_DISK':str(tmp/'progress.disk'),
                   'QOS_BLK_TEST_DELAY_US':'200000'},timeout=20)
        want=f'diskprogress: {"False" if sync else "True"} bytes=4096'
        assert want in p.stdout, p.stdout+p.stderr
    print('Disk wait: legacy path stalls the hart; worker path lets another actor run: PASS')

    if shutil.which('qemu-system-riscv64') and shutil.which('riscv64-unknown-elf-gcc'):
        kernel=tmp/'disk.elf';disk=tmp/'native.disk'
        run(['make','-s','native',f'SYSTEM={ROOT}/tests/disknative.fpr',
             f'KERNEL={kernel}',f'BUILD={tmp}/native'],cwd=ROOT/'qos')
        run(['python3',ROOT/'tools/mkdisk.py',disk,'8'])
        p=run(['qemu-system-riscv64','-machine','virt','-smp','2','-m','256M',
               '-nographic','-bios','none','-kernel',kernel,
               '-drive',f'file={disk},if=none,format=raw,id=hd0',
               '-device','virtio-blk-device,drive=hd0'],timeout=30)
        assert 'native disk: True True' in p.stdout,p.stdout+p.stderr
        print('Native disk: concurrent page buffers and parked completion on RV64/QEMU: PASS')
    else:print('Native disk: SKIP (needs RV64 compiler and QEMU)')
