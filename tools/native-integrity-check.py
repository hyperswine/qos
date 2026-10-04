#!/usr/bin/env python3
"""Native ABI/integrity gates before allocation, then real vector process execution."""
import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, 'FPRISC_ROOT': os.environ.get('FPRISC_ROOT', str(ROOT.parent/'fprisc'))}
ENV.setdefault('XDG_CACHE_HOME', '/tmp/qos-integrity-cache')

def run(args, timeout=240):
    p = subprocess.run(list(map(str, args)), cwd=ROOT, env=ENV, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout[-8000:]}{p.stderr[-8000:]}'
    return p

def hash_checks(out):
    lib = out/'sha256.dylib'
    run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','qos/portable/sha256.c','-o',lib])
    sha = ctypes.CDLL(str(lib))
    sha.qosp_sha256_pair.argtypes = [ctypes.c_void_p,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_uint64,ctypes.c_void_p]
    sha.qosp_sha256.argtypes = [ctypes.c_void_p,ctypes.c_uint64,ctypes.c_void_p]
    for n in (0,1,2,55,56,63,64,65,119,120,127,128,129,4096):
        data = bytes((i*37+11) % 256 for i in range(n))
        expected = hashlib.sha256(data).digest()
        digest = (ctypes.c_ubyte*32)()
        sha.qosp_sha256(data,n,digest)
        assert bytes(digest) == expected, n
        for split in sorted({0,n,n//2,min(1,n),min(55,n),min(63,n),min(64,n),min(65,n)}):
            sha.qosp_sha256_pair(data[:split],split,data[split:],n-split,digest)
            assert bytes(digest) == expected, (n,split)
    print('SHA-256: contiguous/disjoint spans, empty inputs and padding/block boundaries match hashlib HOLDS',flush=True)

def unpack(data):
    end = data.index(b'\n\n')
    payload = data[end+2:]
    return {name.decode():payload[int(off):int(off)+int(size)]
            for name,off,size in (row.split() for row in data[:end].splitlines()[1:])}

def pack(sections):
    offset=0
    rows=[b'QAR2\n']
    for name,data in sections.items():
        rows.append(f'{name} {offset} {len(data)}\n'.encode())
        offset+=len(data)
    return b''.join(rows)+b'\n'+b''.join(sections.values())

def native_checks(out):
    assert all(shutil.which(x) for x in ('qemu-system-riscv64','riscv64-unknown-elf-gcc')), 'Native checks require RV64 compiler and QEMU'
    kernel=out/'kernel.elf'
    run(['make','-s','-C','qos','native',f'SYSTEM={ROOT}/tests/nativeintegrity.fpr',
         f'BUILD={out}/kernel',f'KERNEL={kernel}','NATIVE_CFLAGS_EXTRA=-DQOS_PROCESS_TEST'])
    manifest=out/'CkVector.toml'
    manifest.write_text('name = "CkVector"\nid = "CkVector"\nentry = "n/a"\nloadMode = "process"\nversion = "1"\n')
    original=out/'CkVector.qa'
    run(['tools/build-process-app.sh','tests/vectorproc.fpr',manifest,original])
    sections=unpack(original.read_bytes())
    assert b'nativeabi 3\n' in sections['LOAD'], sections['LOAD']
    assert sections['IMAGE'] and sections['RELOC'] and not sections.get('IMPORT',b'')
    archives=[original]
    variants={}
    for name,section in (('BadImage','IMAGE'),('BadReloc','RELOC')):
        changed=dict(sections)
        data=bytearray(changed[section]);data[len(data)//2]^=1;changed[section]=bytes(data)
        variants[name]=changed
    for name,key in (('NoSha',b'sha '),('NoRelSha',b'relsha ')):
        changed=dict(sections)
        changed['LOAD']=b''.join(row+b'\n' for row in changed['LOAD'].splitlines() if not row.startswith(key))
        variants[name]=changed
    changed=dict(sections);changed['LOAD']=changed['LOAD'].replace(b'nativeabi 3\n',b'nativeabi 2\n');variants['OldAbi']=changed
    changed=dict(sections);changed['IMPORT']=b'c 0 8 fpr_missing\n'
    digest=hashlib.sha256(changed['RELOC']+changed['IMPORT']).hexdigest().encode()
    changed['LOAD']=b''.join((b'relsha '+digest if row.startswith(b'relsha ') else row)+b'\n' for row in changed['LOAD'].splitlines())
    variants['WithImport']=changed
    broken=dict(changed);broken['IMPORT']=changed['IMPORT'].replace(b'missing',b'changed');variants['BadImport']=broken
    for name,parts in variants.items():
        parts=dict(parts)
        parts['MANIFEST']=parts['MANIFEST'].replace(b'CkVector',name.encode())
        qa=out/(name+'.qa');qa.write_bytes(pack(parts));archives.append(qa)
    disk=out/'disk.img';run(['python3','tools/mkdisk.py',disk,'16',*archives])
    for modern in (False,True):
        for harts in (1,2):
            args=['qemu-system-riscv64','-accel','tcg,thread=multi','-machine','virt','-smp',str(harts),
                  '-m','256M','-nographic','-bios','none','-kernel',kernel,
                  '-drive',f'file={disk},if=none,format=raw,id=hd0','-device','virtio-blk-device,drive=hd0']
            if modern: args+=['-global','virtio-mmio.force-legacy=false']
            p=run(args,timeout=120)
            log=p.stdout+p.stderr
            (out/f'virtio{2 if modern else 1}-{harts}h.log').write_text(log)
            assert 'PANIC' not in log and 'FAILED' not in log,log
            for name in variants: assert f'nativeintegrity: {name} refused=True' in log,log
            assert 'nativeintegrity: process=[vectorproc: generic=2.5 nested=3.5,4.5,7 fold=91] images=0 allocations=1 HOLDS' in log,log
            print(f'Native integrity/ABI/vector process: virtio {2 if modern else 1}, {harts} hart(s) HOLDS',flush=True)
    obj=out/'production.o'
    run(['riscv64-unknown-elf-gcc','-march=rv64imafdc_zicsr','-mabi=lp64','-mcmodel=medany',
         '-ffreestanding','-O2',f'-I{ENV["FPRISC_ROOT"]}/runtime','-c','loader/process.c','-o',obj])
    assert 'testImageAllocs' not in run(['riscv64-unknown-elf-nm',obj]).stdout
    print('Production placement object has no test allocation counter HOLDS',flush=True)

def check(out,hash_only=False):
    hash_checks(out)
    if not hash_only: native_checks(out)

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--hash-only',action='store_true')
    args=parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True,exist_ok=True);check(args.output.resolve(),args.hash_only)
    else:
        with tempfile.TemporaryDirectory(prefix='qos-native-integrity-') as directory:
            check(Path(directory),args.hash_only)
