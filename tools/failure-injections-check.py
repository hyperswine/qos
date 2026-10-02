#!/usr/bin/env python3
"""Audit failure injections: native TX stall/orphan, full console pipe,
full/dead storage mailbox across the native process ABI and routed failure.
Artifacts are temporary unless --output retains them. Native probes boot
one and two harts, with legacy and modern virtio devices.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ)
ENV.setdefault('FPRISC_ROOT', str(ROOT.parent / 'fprisc'))
ENV.setdefault('XDG_CACHE_HOME', '/tmp/qos-failure-cache')

def run(args, cwd=ROOT, timeout=240):
    try:
        p = subprocess.run(list(map(str, args)), cwd=cwd, env=ENV,
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as error:
        raise AssertionError(f"{args}: timeout\n{error.stdout!r}\n{error.stderr!r}") from error
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout[-8000:]}{p.stderr[-8000:]}'
    return p

def boot(kernel, disk=None, net=False, harts=1, modern=False):
    args = ['qemu-system-riscv64', '-machine', 'virt', '-smp', str(harts), '-m', '256M',
            '-nographic', '-bios', 'none', '-kernel', kernel]
    if modern:
        args += ['-global', 'virtio-mmio.force-legacy=false']
    if disk:
        args += ['-drive', f'file={disk},if=none,format=raw,id=hd0', '-device', 'virtio-blk-device,drive=hd0']
    if net:
        args += ['-netdev', 'user,id=n0', '-device', 'virtio-net-device,netdev=n0']
    p = run(args, timeout=40)
    assert 'PANIC' not in p.stdout + p.stderr and 'HOLDS' in p.stdout and 'FAILED' not in p.stdout, p.stdout + p.stderr
    return p.stdout

def check(out, names):
    console = out / 'console'
    run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread', '-Ihal/unix',
         'tests/host/console_full_check.c', 'hal/unix/hostlog.c', '-o', console])
    p = run([console], timeout=5)
    assert 'HOLDS' in p.stdout, p.stdout
    assert p.stderr.count('console not writable within 20 ms') == 2, p.stderr
    assert '5000 byte(s) dropped' in p.stderr and '1 byte(s) dropped' in p.stderr, p.stderr
    print(p.stdout.strip(), flush=True)
    if not all(shutil.which(x) for x in ('qemu-system-riscv64', 'riscv64-unknown-elf-gcc')):
        print('Native injections: SKIP (needs RV64 compiler and QEMU)')
    else:
        # Test entry points must not exist in ordinary production objects.
        compiler = Path(ENV['FPRISC_ROOT'])
        for source in ('hal/virt/net.c', 'loader/process.c'):
            obj = out / (Path(source).stem + '.o')
            run(['riscv64-unknown-elf-gcc', '-march=rv64imafdc_zicsr', '-mabi=lp64',
                 '-mcmodel=medany', '-ffreestanding', '-O2', f'-I{compiler}/runtime',
                 f'-I{compiler}/machine/virt', '-c', source, '-o', obj])
            symbols = run(['riscv64-unknown-elf-nm', obj]).stdout
            assert 'netTest' not in symbols and 'testFillFrom' not in symbols, symbols
        print('Production objects: injection entry points absent HOLDS', flush=True)
        for name in names:
            kernel = out / (name + '.elf')
            flags = '-DQOS_NET_TEST -DNET_DEADLINE_TICKS=3000000ULL' if name.startswith('net') else '-DQOS_PROCESS_TEST'
            run(['make', '-s', '-C', 'qos', 'native', f'SYSTEM={ROOT}/tests/{name}.fpr',
                 f'KERNEL={kernel}', f'BUILD={out}/{name}', f'NATIVE_CFLAGS_EXTRA={flags}'])
            disk = None
            if name == 'nativerefusal':
                archives = []
                for identity, source in (('CkSlow', 'storeprobe'), ('CkFail', 'failproc')):
                    manifest = out / (identity + '.toml')
                    manifest.write_text(f'name = "{identity}"\nid = "{identity}"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n')
                    qa = out / (identity + '.qa')
                    run(['tools/build-process-app.sh', f'tests/{source}.fpr', manifest, qa])
                    archives.append(qa)
                disk = out / 'disk'
                run(['python3', 'tools/mkdisk.py', disk, '8', *archives])
            for modern in (False, True):
                for harts in (1, 2):
                    log = boot(kernel, disk, name.startswith('net'), harts, modern)
                    assert name + ':' in log, log
                    reason = {'netstall': 'transmit timed out', 'netorphan': 'stalled on an abandoned frame',
                              'nativerefusal': 'actor failed: blk: page out of range'}[name]
                    assert reason in log, log
                    (out / f'{name}-v{2 if modern else 1}-{harts}h.log').write_text(log)
                    print(f'{name}: virtio v{2 if modern else 1}, {harts} hart(s)', flush=True)
                    print(log.strip(), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--only', nargs='+', choices=['netstall', 'netorphan', 'nativerefusal'],
                        default=['netstall', 'netorphan', 'nativerefusal'])
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        check(args.output.resolve(), args.only)
    else:
        with tempfile.TemporaryDirectory(prefix='qos-failure-') as tmp:
            check(Path(tmp), args.only)
