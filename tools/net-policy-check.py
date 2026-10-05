#!/usr/bin/env python3
"""Execute raw RV64 TCP/ARP policy through its real C ABI against packet fixtures."""
from pathlib import Path
import os
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
COMPILER = Path(os.environ.get('FPRISC_ROOT') or (ROOT / 'fprisc.path').read_text().strip())
def run(args, cwd=ROOT, timeout=180):
    p = subprocess.run(list(map(str,args)), cwd=cwd, capture_output=True,text=True,timeout=timeout)
    assert p.returncode==0, f'{args}: {p.stdout}{p.stderr}'
    return p.stdout+p.stderr
with tempfile.TemporaryDirectory(prefix='qos-netpolicy-') as d:
    temp=Path(d)
    for bits in (32,64):
        obj=temp/f'net-{bits}.o'
        run(['riscv64-unknown-elf-gcc',f'-march=rv{bits}imafdc_zicsr','-mabi=ilp32' if bits==32 else '-mabi=lp64',
             '-mcmodel=medany','-ffreestanding','-O2',f'-I{COMPILER}/runtime',f'-I{COMPILER}/machine/virt',
             '-c',ROOT/'hal/virt/net.c','-o',obj])
        symbols=run(['riscv64-unknown-elf-nm',obj])
        assert 'netTest' not in symbols,symbols
        assert ('qos_net_receive' in symbols)==(bits==64),symbols
        print(f'RV{bits} network object: expected policy ABI, no test hooks HOLDS',flush=True)
    run(['make','-s','-f','hal/virt/qos-virt.mk',f'FPRC={COMPILER}/fpr',f'BUILD={temp}','QOS_HAL=hal',temp/'qos-netpolicy.s'])
    for harts in (1,2):
        image=temp/f'probe-{harts}.elf'
        run(['make','-s','bare-metal',f'PROG={ROOT}/tests/netpolicy.fpr',f'BUILD={temp}/image-{harts}',f'IMAGE={image}',
             f'HARTS={harts}',f'EXTRA_RT={temp}/qos-netpolicy.s {ROOT}/tests/host/netpolicy_check.c'],cwd=COMPILER)
        out=run(['qemu-system-riscv64','-machine','virt','-smp',harts,'-m','128M','-nographic','-bios','none','-kernel',image],timeout=30)
        assert 'netpolicy: packets, checksums, bounds, state and backpressure HOLDS' in out,out
        print(f'Raw TCP/ARP: {harts} hart(s), packet/checksum/refusal/state fixtures HOLDS',flush=True)

    # A checksum-blind parser must be rejected by the corrupt packet fixture.
    mutant=temp/'mutant.fpr'
    src=(ROOT/'hal/virt/netpolicy.fpr').read_text()
    guard='if checksum tcp count seed != 0 then 0 else'
    assert guard in src
    mutant.write_text(src.replace(guard,'if False then 0 else'))
    raw=temp/'mutant.s'
    exports='receive:qos_net_receive,emit:qos_net_emit,poll:qos_net_poll,readSize:qos_net_read_size,consume:qos_net_consume,segment:qos_net_segment,connection:qos_net_connection,close:qos_net_close'
    run([COMPILER/'fpr','--profile=bare-metal-builtin','--arc','--raw','--lib',f'--export={exports}',mutant,raw])
    image=temp/'mutant.elf'
    run(['make','-s','bare-metal',f'PROG={ROOT}/tests/netpolicy.fpr',f'BUILD={temp}/mutant-build',f'IMAGE={image}',
         'HARTS=1',f'EXTRA_RT={raw} {ROOT}/tests/host/netpolicy_check.c'],cwd=COMPILER)
    p=subprocess.run(['qemu-system-riscv64','-machine','virt','-smp','1','-m','128M','-nographic','-bios','none','-kernel',str(image)],capture_output=True,text=True,timeout=30)
    assert 'netpolicy failed at check' in p.stdout+p.stderr,p.stdout+p.stderr
    print('Raw TCP/ARP: checksum-blind mutation rejected HOLDS',flush=True)
