#!/usr/bin/env python3
"""Real RV64 process-plane inbox admission and ARC/linear ownership."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
FPR = Path(os.environ.get('FPRISC_ROOT', ROOT.parent/'fprisc'))
with tempfile.TemporaryDirectory(prefix='qos-native-inbox-') as tmp:
    out = Path(tmp)
    env = dict(os.environ,FPRISC_ROOT=str(FPR),XDG_CACHE_HOME=str(out/'cache'))
    def run(args, timeout=240):
        p = subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
        assert p.returncode == 0,p.stdout+p.stderr
        return p.stdout+p.stderr
    # Test-only C pointer observation linked into the process, with no new
    # production primitive or change to the standard process builder.
    script = (ROOT/'tools/build-process-app.sh').read_text()
    line = next(x for x in script.splitlines() if x.startswith('ROOT='))
    script = script.replace(line,'ROOT='+shlex.quote(str(ROOT)))
    script = script.replace('RT="$VIRT_FPR', 'RT="'+str(FPR/'tests/base/inbox_probe.c')+' $VIRT_FPR')
    builder = out/'build-process.sh';builder.write_text(script);builder.chmod(0o755)
    manifest = out/'CkInbox.toml'
    manifest.write_text('name = "CkInbox"\nid = "CkInbox"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n')
    qa = out/'CkInbox.qa'
    run([builder,'tests/inboxproc.fpr',manifest,qa])
    for harts in (1,2):
        kernel = out/f'kernel-{harts}.elf'
        run(['make','-s','-C','qos','native',f'SYSTEM={ROOT}/tests/nativeinbox.fpr',f'KERNEL={kernel}',f'BUILD={out}/build-{harts}',f'HARTS={harts}'])
        for modern in (False,True):
            disk=out/f'disk-{harts}-{modern}'
            run(['python3','tools/mkdisk.py',disk,8,qa])
            args=['qemu-system-riscv64','-machine','virt','-smp',str(harts),'-m','256M','-nographic','-bios','none','-kernel',kernel,
                  '-drive',f'file={disk},if=none,format=raw,id=hd0','-device','virtio-blk-device,drive=hd0']
            if modern: args += ['-global','virtio-mmio.force-legacy=false']
            text = run(args,30)
            assert 'image reclamation HOLDS' in text and 'PANIC' not in text,text
            print(f'Native inbox/process ownership: virtio v{2 if modern else 1}, {harts} hart(s) HOLDS',flush=True)
