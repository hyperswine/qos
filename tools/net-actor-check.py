#!/usr/bin/env python3
"""Network owner lifecycle under Portable and native v1/v2, target-matched harts."""
from pathlib import Path
import os, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
def run(args,cwd=ROOT,env=None,timeout=240):
    p=subprocess.run(list(map(str,args)),cwd=cwd,env={**os.environ,**(env or {})},capture_output=True,text=True,timeout=timeout)
    assert p.returncode==0,f'{args}: {p.stdout}{p.stderr}'
    return p.stdout+p.stderr
with tempfile.TemporaryDirectory(prefix='qos-netactor-') as d:
    temp=Path(d);host=temp/'qosp';app=temp/'netactor.qa'
    run(['make','-s','portable',f'QOSP_OUT={host}'],cwd=ROOT/'qos')
    for entry in ('netactor', 'netactorstart'):
      run(['make','-s','qos-app',f'PROG=tests/{entry}.fpr',f'QA_OUT={app}',f'BUILD={temp}/portable-{entry}'])
      for harts in (1,2):
        out=run([host,'--yes',app],cwd=temp,env={'FPR_HARTS':str(harts),'FPR_PORT':'0'})
        assert ('noRestart=True HOLDS' if entry=='netactor' else 'responsive=True HOLDS') in out and 'FAILED' not in out,out
        print(f'Portable network actor ({entry}): {harts} harts lifecycle HOLDS',flush=True)
        kernel=temp/f'net-{harts}.elf'
        run(['make','-s','native',f'SYSTEM={ROOT}/tests/{entry}.fpr',f'KERNEL={kernel}',f'BUILD={temp}/native-{entry}-{harts}',f'HARTS={harts}'],cwd=ROOT/'qos')
        for modern in (False,True):
            args=['qemu-system-riscv64','-machine','virt','-smp',harts,'-m','256M','-nographic','-bios','none','-kernel',kernel,
                  '-netdev','user,id=n0','-device','virtio-net-device,netdev=n0']
            if modern:args+=['-global','virtio-mmio.force-legacy=false']
            out=run(args,timeout=30)
            assert ('noRestart=True HOLDS' if entry=='netactor' else 'responsive=True HOLDS') in out and 'FAILED' not in out,out
            print(f'Native network actor ({entry}): v{2 if modern else 1}, {harts} harts lifecycle HOLDS',flush=True)
