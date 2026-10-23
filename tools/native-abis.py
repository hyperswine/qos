#!/usr/bin/env python3
"""Read the runtime contract versions selected by the process C target.

Header text can contain several conditional definitions. Preprocess with the
same RV64 integer ABI as build-process-app.sh instead of taking the first one.
"""
import argparse,re,subprocess
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('fprisc',type=Path)
    args=ap.parse_args()
    header=args.fprisc.resolve()/'runtime/fpr.h'
    result=subprocess.run(['riscv64-unknown-elf-gcc','-march=rv64imafdc_zicsr','-mabi=lp64',
                           '-DFPR_NHARTS=1','-ffreestanding','-dM','-E','-x','c','-include',str(header),'-'],
                          input='',capture_output=True,text=True,check=True,timeout=30)
    values=[]
    for name in ('FPR_NATIVE_ABI','FPR_PLANE_ACTORS_ABI','FPR_PLANE_MEMORY_ABI'):
        match=re.search(r'^#define '+name+r' (\d+)u?$',result.stdout,re.M)
        if match is None:ap.error('target does not define a numeric '+name)
        values.append(match[1])
    print(' '.join(values))

if __name__=='__main__':main()
