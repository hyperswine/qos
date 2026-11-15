from pathlib import Path
import struct,hashlib,sys,os
root=Path(os.environ['SIMPLE_RISC'])/'output/tangnano20k/btbdef-54'
src=(root/'impl/pnr/sdram_test.fs').read_bytes()
assert hashlib.sha256(src).hexdigest()=='f01fdf0bb48c3f5842cf8f8ad0d7d24bc1a746c9959993089e26a4661e207038'
lines=src.decode().splitlines()
indices=[i for i,l in enumerate(lines) if len(l)==3440]
rows=[bytearray(lines[i][:3376],'ascii') for i in indices]
old=b''.join(int(l,16).to_bytes(4,'little') for l in (root/'bootrom-sdram.hex').read_text().split())
new=Path('rom.bin').read_bytes().ljust(2048,b'\0')
def cols(data):
 v=[bytearray(256) for _ in range(64)]
 for i in range(16384):
  r=[0,128,64,192][(i>>4)&3]+((i>>6)&63)
  v[(i>>12)*16+i%16][r]=48+((data[i//8]>>(i%8))&1)
 return v
o,n=cols(old),cols(new)
columns=list(map(bytes,zip(*rows)))
from collections import Counter
hits=Counter()
for c in o:
 for col in columns:
  for rev in [False,True]:
   j=col.find(c[::-1] if rev else c)
   if j>=0:hits[j,rev]+=1
print(hits.most_common(5))
if not hits:sys.exit(1)
start,rev=hits.most_common(1)[0][0]
for j,c in enumerate(o):
 sig=c[::-1] if rev else c
 found=[k for k,col in enumerate(columns) if col[start:start+256]==sig]
 if len(found)!=1:raise ValueError((j,len(found)))
 for r,b in enumerate(n[j][::-1] if rev else n[j]): rows[start+r][found[0]]=b
def crc(data):
 c=0
 for b in data:
  c^=b
  for _ in range(8):c=(c>>1)^((0-(c&1))&0xa001)
 return c
for i,row in zip(indices,rows):
 if lines[i][:3376]==row.decode():continue
 before=int(lines[i][:3376],2).to_bytes(422,'big')
 after=int(row,2).to_bytes(422,'big')
 suffix=int(lines[i][-64:],2).to_bytes(8,'big')
 seed=int(lines[i-1][-48:],2).to_bytes(6,'big')
 assert crc(seed+before)==int.from_bytes(suffix[:2],'little')
 lines[i]=row.decode()+f'{int.from_bytes(crc(seed+after).to_bytes(2,"little")+suffix[2:],"big"):064b}'
def cs(rows):return sum(sum(struct.unpack('>211H',int(r,2).to_bytes(422,'big'))) for r in rows)&65535
print('checksums all frames old/new:',hex(cs([l[:3376] for l in src.decode().splitlines() if len(l)==3440])),hex(cs(rows)))
Path('patched-pre.fs').write_text('\n'.join(lines)+'\n')
