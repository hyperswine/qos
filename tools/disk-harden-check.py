#!/usr/bin/env python3
"""Disk failure and lifecycle hardening (docs/2026-10-01-DISK-HARDENING.md).

Native (a test kernel, -DQOS_BLK_TEST, 0.3 s deadline): a request the device
never completes fail-stops its owner; the next request resets the device past
the deadline and proceeds; an owner killed mid-request keeps its buffers
reserved until the reset; a reset that fails takes the disk offline and a later
request is refused at once.

Portable (a -DQOS_BLK_TEST host, an app with a 0.3 s deadline): the storage
actor that meets a stalled disk fail-stops and its client gets an Err; a caller
past its deadline fail-stops; a request while the worker is stalled is refused;
after the worker drains, writes and reads land."""
import os, shutil, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def run(args, cwd=ROOT, env=None, timeout=300):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env={**os.environ, **(env or {})},
                       capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout}{p.stderr}'
    return p

with tempfile.TemporaryDirectory(prefix='qos-disk-harden-') as d:
    tmp = Path(d)
    host = tmp / 'host'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}', 'FPRBUILD_EXTRA=--cflag -DQOS_BLK_TEST'], cwd=ROOT / 'qos')
    run(['make', '-s', 'qos-app', 'PROG=tests/diskstallp.fpr', f'BUILD={tmp}/app', f'QA_OUT={tmp}/stall.qa',
         'QOSCFLAGS_EXTRA=-DQOS_BLK_DEADLINE_TICKS=3000000ULL'])
    p = run([host, '--yes', tmp / 'stall.qa'], cwd=tmp, timeout=60,
            env={'FPR_HARTS': '2', 'FPR_DISK': str(tmp / 'stall.disk'), 'QOS_BLK_TEST_DELAY_US': '800000',
                 'QOS_BLK_TEST_DELAY_READS': '2', 'QOS_BLK_DEADLINE_MS': '300'})
    assert 'diskstallp: storage=Err storage service: dead actor timeout=Err dead actor refused=Err dead actor write=Ok 5 read=Ok fresh HOLDS' in p.stdout, p.stdout + p.stderr
    print('Portable disk: a stalled disk fail-stops the storage actor (its client gets Err), a late caller, refuses while stalled, recovers: PASS')

    if shutil.which('qemu-system-riscv64') and shutil.which('riscv64-unknown-elf-gcc'):
        kernel = tmp / 'stall.elf'; disk = tmp / 'native.disk'
        run(['make', '-s', 'native', f'SYSTEM={ROOT}/tests/diskstall.fpr', f'KERNEL={kernel}', f'BUILD={tmp}/native',
             'NATIVE_CFLAGS_EXTRA=-DQOS_BLK_TEST -DBLK_DEADLINE_TICKS=3000000ULL'], cwd=ROOT / 'qos')
        run(['python3', ROOT / 'tools/mkdisk.py', disk, '8'])
        p = run(['qemu-system-riscv64', '-machine', 'virt', '-smp', '2', '-m', '256M', '-nographic', '-bios', 'none',
                 '-kernel', kernel, '-drive', f'file={disk},if=none,format=raw,id=hd0',
                 '-device', 'virtio-blk-device,drive=hd0'], timeout=60)
        out = p.stdout
        assert 'diskstall: stalled=Err dead actor after-reset=before rewrite=rewrit cancel=afterk' in out and out.rstrip().endswith('HOLDS'), out + p.stderr
        assert 'fast=True' in out and 'disk offline' in out, out
        print('Native disk: stalled owner fail-stops, reset past the deadline, killed owner, failed reset -> offline -> refused: PASS')
    else:
        print('Native disk: SKIP (needs RV64 compiler and QEMU)')
