#!/usr/bin/env python3
"""Loaded processes reuse the kernel's network owner and release their images."""
from pathlib import Path
import os, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
COMPILER=os.environ.get('FPRISC_ROOT') or (ROOT/'fprisc.path').read_text().strip()
def run(args,cwd=ROOT,timeout=240):
    try:
        p=subprocess.run(list(map(str,args)),cwd=cwd,env={**os.environ,'FPRISC_ROOT':COMPILER},capture_output=True,text=True,timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise AssertionError(f'timeout: {e.stdout!r} {e.stderr!r}') from e
    assert p.returncode==0,f'{args}: {p.stdout}{p.stderr}'
    return p.stdout+p.stderr
with tempfile.TemporaryDirectory(prefix='qos-netprocess-') as d:
    temp=Path(d);manifest=temp/'NetOwner.toml';qa=temp/'NetOwner.qa'
    manifest.write_text('name = "NetOwner"\nid = "NetOwner"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n')
    run(['tools/build-process-app.sh','tests/netactorprocess.fpr',manifest,qa])
    for harts in (1,2):
        kernel=temp/f'kernel-{harts}.elf'
        run(['make','-s','native',f'SYSTEM={ROOT}/tests/native-netowner.fpr',f'KERNEL={kernel}',f'BUILD={temp}/build-{harts}',f'HARTS={harts}'],cwd=ROOT/'qos')
        for modern in (False,True):
            disk=temp/f'disk-{harts}-{modern}'
            run(['python3',ROOT/'tools/mkdisk.py',disk,'8',qa])
            args=['qemu-system-riscv64','-machine','virt','-smp',harts,'-m','256M','-nographic','-bios','none','-kernel',kernel,
                  '-drive',f'file={disk},if=none,format=raw,id=d0','-device','virtio-blk-device,drive=d0',
                  '-netdev','user,id=n0','-device','virtio-net-device,netdev=n0']
            if modern:args+=['-global','virtio-mmio.force-legacy=false']
            out=run(args,timeout=30)
            assert 'netactorprocess: kernel=True actual=True same=True status=True noPeer=True denied=True guarded=True HOLDS' in out,out
            assert 'freed=True alive=True HOLDS' in out and 'FAILED' not in out,out
            print(f'Loaded process network owner: v{2 if modern else 1}, {harts} harts, shared actor and image release HOLDS',flush=True)
