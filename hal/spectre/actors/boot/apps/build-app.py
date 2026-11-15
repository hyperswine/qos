"""Build the small Spectre returning-app ABI: PC-relative text and read-only literals."""
import re,subprocess as sp,sys,struct,zlib
from pathlib import Path
mailbox = sys.argv[3:] == ["--mailbox"]
if sys.argv[3:] and not mailbox: raise SystemExit("expected optional --mailbox")
src=Path(sys.argv[1]);base=src.stem
def run(args):sp.run(args,check=True)
run([sys.argv[2],'compile','--profile=builtin','--target=rv32','--prelude=empty.fpr',str(src),base+'.s'])
s=Path(base+'.s').read_text()
s=re.sub(r'(?m)^# fn (\S+).*?\n(?=    \.globl (fpr_fn_\w+))',lambda m:m[0]+'.section .text.'+m[2]+',"ax"\n',s)
s=re.sub(r'(?m)^# static-pap:', '.section .rodata.paps,"a"\n# static-pap:',s)
# The compiler's typed RV32 blocks include tail-recursive loop targets.
s,count=re.subn(r'(?m)^(\.Ltir_\w+_b[0-9]+:)$',r'\1\n    addi sp,sp,-16\n    sw ra,12(sp)\n    call spectre_poll\n    lw ra,12(sp)\n    addi sp,sp,16',s)
if not count:raise ValueError("No instrumentable typed blocks")
Path(base+'.sections.s').write_text(s)
cc=['riscv64-unknown-elf-gcc','-march=rv32im','-mabi=ilp32','-mno-relax','-nostdlib','-Wl,--gc-sections,--emit-relocs','-T','link.ld']
if mailbox: cc.append('-DSPECTRE_MAILBOX')
run(cc+['entry.S',base+'.sections.s','-o',base+'.elf'])
rel=sp.check_output(['riscv64-unknown-elf-readelf','-rW',base+'.elf'],text=True)
for kind in re.findall(r'\bR_RISCV_\w+',rel):
 if kind not in {'R_RISCV_PCREL_HI20','R_RISCV_PCREL_LO12_I','R_RISCV_CALL','R_RISCV_CALL_PLT','R_RISCV_BRANCH','R_RISCV_JAL','R_RISCV_NONE'}:raise ValueError(kind)
run(['riscv64-unknown-elf-objcopy','-O','binary',base+'.elf',base+'.bin'])
b=Path(base+'.bin').read_bytes();assert 0<len(b)<=4096
Path(base+'.sxa').write_text((struct.pack('<4sII',b'SXA3' if mailbox else b'SXA2',len(b),zlib.crc32(b))+b).hex())
