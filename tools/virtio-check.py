#!/usr/bin/env python3
"""RV64 raw virtio unit against an independent memory-backed C reference."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER = Path(os.environ.get('FPRISC_ROOT') or ((ROOT / 'fprisc.path').read_text().strip() if (ROOT / 'fprisc.path').exists() else ROOT.parent / 'fprisc'))

def run(args, cwd=ROOT, timeout=180):
    p = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout}\n{p.stderr}'
    return p.stdout + p.stderr

with tempfile.TemporaryDirectory(prefix='qos-virtio-') as temp:
    build = Path(temp)
    run(['make', '-s', '-f', 'hal/virt/qos-virt.mk', f'FPRC={COMPILER}/fpr',
         f'BUILD={build}', 'QOS_HAL=hal', build / 'qos-virtio.s', build / 'qos-blockpolicy.s'])
    image = build / 'probe.elf'
    run(['make', '-s', 'bare-metal', f'PROG={ROOT}/tests/virtio.fpr', f'BUILD={build}/image',
         f'IMAGE={image}', f'EXTRA_RT={build}/qos-virtio.s {build}/qos-blockpolicy.s {ROOT}/tests/host/virtio_check.c'], cwd=COMPILER)
    for harts in (1, 2):
        out = run(['qemu-system-riscv64', '-machine', 'virt', '-smp', harts, '-m', '128M',
                   '-nographic', '-bios', 'none', '-kernel', image], timeout=30)
        assert 'virtio: probe, features, queue parity and refusal HOLDS' in out, out
        print(f'virtio memory-backed differential: {harts} hart(s) HOLDS', flush=True)
