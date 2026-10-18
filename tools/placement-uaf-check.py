#!/usr/bin/env python3
"""Process placement keeps its image until it is out of the entry (review I-6).

loader/process.c placed an image, called its entry (which spawns the root
actor) and only then read the root and the refusal out of the image's own
record.  If the root ran and ended first (on another hart, or while the
launcher was descheduled), its quiet freed the block and those reads, and
the entry's epilogue, ran on freed memory.  The record is now pinned
(`placing`) until the launcher is done with it.

tests/placeuaf.fpr (built with -DQOS_PROCESS_TEST) makes the launcher wait
300 ms after the entry so the root ends first, every time; a test build
poisons a freed record.  Three placements on 1 and 2 harts must each
return the process's own answer, and every image must go home.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, 'FPRISC_ROOT': os.environ.get('FPRISC_ROOT', str(ROOT.parent / 'fprisc'))}


def run(args, timeout=300):
    try:
        p = subprocess.run(list(map(str, args)), cwd=ROOT, env=ENV, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # the unpinned record, freed and poisoned, hands the launcher a
        # garbage root: it waits for an answer that never comes
        raise AssertionError(f'{args[0]}: no verdict in {timeout}s\n{(e.stdout or b"")[-3000:]!r}')
    out = p.stdout + p.stderr
    assert p.returncode == 0, f'{args}: {p.returncode}\n{out[-6000:]}'
    return out


if not all(shutil.which(x) for x in ('qemu-system-riscv64', 'riscv64-unknown-elf-gcc')):
    print('placement-uaf: SKIP (needs RV64 compiler and QEMU)')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='qos-placement-uaf-') as name:
    tmp = Path(name)
    manifest = tmp / 'CkVector.toml'
    manifest.write_text('name = "CkVector"\nid = "CkVector"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n')
    qa = tmp / 'CkVector.qa'
    run(['tools/build-process-app.sh', 'tests/vectorproc.fpr', manifest, qa])
    disk = tmp / 'disk.img'
    run(['python3', 'tools/mkdisk.py', disk, '16', qa])
    kernel = tmp / 'kernel.elf'
    run(['make', '-s', '-C', 'qos', 'native', f'SYSTEM={ROOT}/tests/placeuaf.fpr', f'BUILD={tmp}/kernel',
         f'KERNEL={kernel}', 'NATIVE_CFLAGS_EXTRA=-DQOS_PROCESS_TEST'])
    for harts in (1, 2):
        log = run(['qemu-system-riscv64', '-accel', 'tcg,thread=multi', '-machine', 'virt', '-smp', str(harts),
                   '-m', '256M', '-nographic', '-bios', 'none', '-kernel', kernel,
                   '-drive', f'file={disk},if=none,format=raw,id=hd0', '-device', 'virtio-blk-device,drive=hd0'],
                  timeout=180)
        assert 'PANIC' not in log and 'placeuaf: delayed placement x3, images=0 HOLDS' in log, log[-4000:]
        print(f'placement-uaf ({harts} hart(s)): the root ends before placement reads its record, x3: PASS', flush=True)
print('placement-uaf: PASS')
