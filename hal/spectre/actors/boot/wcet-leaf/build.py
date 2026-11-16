"""Build a bounded measurement app from FP-RISC compiler output."""
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

apps = Path(sys.argv[2]).resolve()
subprocess.run([sys.argv[1], 'compile', '--profile=builtin', '--target=rv32',
                '--prelude=' + str(apps / 'empty.fpr'), 'leaf.fpr', 'leaf.s'], check=True)
asm = Path('leaf.s').read_text()
# Isolate the complete compiler-emitted function without its unused runtime.
body = re.search(r'^    \.globl fpr_fn_chooseRight\n.*?^# native-insns-v1: chooseRight .*?$',
                 asm, re.M | re.S)
if not body:
    raise ValueError('missing compiler function')
Path('body.s').write_text('.text\n' + body[0] + '\n')
subprocess.run(['riscv64-unknown-elf-gcc', '-march=rv32im_zicsr', '-mabi=ilp32',
                '-mno-relax', '-nostdlib', '-T', str(apps / 'link.ld'),
                'entry.S', 'body.s', '-o', 'leaf.elf'], check=True)
subprocess.run(['riscv64-unknown-elf-objcopy', '-O', 'binary', 'leaf.elf', 'leaf.bin'],check=True)
data = Path('leaf.bin').read_bytes()
Path('leaf.sxa').write_text((struct.pack('<4sII', b'SXA2', len(data), zlib.crc32(data))+data).hex())
