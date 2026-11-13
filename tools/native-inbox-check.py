#!/usr/bin/env python3
"""Real RV64 process-plane inbox admission and ARC/linear ownership."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
FPR = Path(os.environ.get('FPRISC_ROOT', ROOT.parent/'fprisc'))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--credit-check', action='store_true',
                    help='run one two-hart modern virtio boot with sender credits enabled')
credit = parser.parse_args().credit_check
with tempfile.TemporaryDirectory(prefix='qos-native-inbox-') as tmp:
    out = Path(tmp)
    env = dict(os.environ,FPRISC_ROOT=str(FPR),XDG_CACHE_HOME=str(out/'cache'))
    def run(args, timeout=240):
        p = subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
        assert p.returncode == 0,p.stdout+p.stderr
        return p.stdout+p.stderr
    # Test-only C pointer observation linked into the process, with no new
    # production primitive or change to the standard process builder.
    link_inputs = [FPR / 'tests/base/inbox_probe.c']
    if credit:
        link_inputs.append('-DFPR_SENDER_CREDITS=1')
    manifest = out/'CkInbox.toml'
    manifest.write_text('name = "CkInbox"\nid = "CkInbox"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n')
    qa = out/'CkInbox.qa'
    run([os.environ.get('SOL', 'sol'), 'tools/build-process-app.sol',
         'tests/inboxproc.fpr', manifest, qa, '--', *link_inputs])
    assembly = (ROOT/'build/inboxproc.s').read_text()
    builder_body = assembly.split('\nfpr_fn_build:\n', 1)[1].split('\n# fn ', 1)[0]
    assert 'call fpr_g_Sys_x2esendConcat_call3' in builder_body and 'fpr_prim_fn_strcat' not in builder_body
    pair_body = assembly.split('\nfpr_fn_pairProducer:\n', 1)[1].split('\n# fn ', 1)[0]
    assert 'call fpr_g_Sys_x2esendIntPair_call3' in pair_body
    for harts in ((2,) if credit else (1,2)):
        kernel = out/f'kernel-{harts}.elf'
        run(['make','-s','-C','qos','native',f'SYSTEM={ROOT}/tests/nativeinbox.fpr',f'KERNEL={kernel}',f'BUILD={out}/build-{harts}',f'HARTS={harts}', *(['NATIVE_CFLAGS_EXTRA=-DFPR_SENDER_CREDITS=1'] if credit else [])])
        for modern in ((True,) if credit else (False,True)):
            disk=out/f'disk-{harts}-{modern}'
            run([os.environ.get("SOL", "sol"),'tools/mkdisk.sol',disk,8,qa])
            args=['qemu-system-riscv64','-machine','virt','-smp',str(harts),'-m','256M','-nographic','-bios','none','-kernel',kernel,
                  '-drive',f'file={disk},if=none,format=raw,id=hd0','-device','virtio-blk-device,drive=hd0']
            if modern: args += ['-global','virtio-mmio.force-legacy=false']
            text = run(args,30)
            assert 'image reclamation HOLDS' in text and 'PANIC' not in text,text
            print(f'Native inbox/process ownership: virtio v{2 if modern else 1}, {harts} hart(s) HOLDS',flush=True)
