"""Check the linked path and every raw sample before summarizing costs."""
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess

def disassemble(*args):
    return subprocess.check_output(['riscv64-unknown-elf-objdump', '-d', '-M',
                                    'no-aliases', *args, 'leaf.elf'], text=True)

def ops(text):
    return re.findall(r'^\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(\S+)\s*(.*)$', text, re.M)

body = ops(disassemble('--disassemble=fpr_fn_chooseRight'))
expected = ['addi','sw','sw','addi','addi','addi','lw','lw','addi','jalr']
assert [op for _,op,_ in body] == expected
assert body[-1][2].strip() == 'zero,0(ra)'
all_ops = ops(disassemble())
i = next(i for i,(_,op,args) in enumerate(all_ops) if op=='csrrs' and 's4,mcycle,zero' in args)
window = all_ops[i:i+5]
assert [op for _,op,_ in window] == ['csrrs','csrrs','jalr','csrrs','csrrs']
assert [x[2].strip() for x in window] == ['s4,mcycle,zero','s5,minstret,zero','ra,0(s2)','t0,minstret,zero','t1,mcycle,zero']
rows = [(int(c,16),int(n,16)) for c,n in re.findall(
    r'W ([a-f0-9]{8}) ([a-f0-9]{8})',Path('board.log').read_text())]
assert len(rows)==32 and 'exit 42' in Path('board.log').read_text()
summary = {}
for label, samples, length in [('ret_only',rows[::2],1),('chooseRight',rows[1::2],len(body))]:
    assert all(n==2+length for _,n in samples)
    summary[label] = {'paired_trials':len(samples),'minstret_delta':2+length,
                      'raw_mcycle_histogram':dict(collections.Counter(c for c,_ in samples))}
print(json.dumps({'elf_sha256':hashlib.sha256(Path('leaf.elf').read_bytes()).hexdigest(),
                  'package_sha256':hashlib.sha256(Path('leaf.sxa').read_bytes()).hexdigest(),
                  'leaf_link_offset':body[0][0],'samples':summary},indent=2))
