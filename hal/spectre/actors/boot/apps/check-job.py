import os,re,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(os.environ['SIMPLE_RISC'])/'boards/tangnano20k'))
from run_program import open_port
import rom_protocol as rom
fd=open_port(os.environ.get('SPECTRE_UART','/dev/cu.usbserial-20250303171'),round(54e6/868));t=rom.FdTransport(fd)
def until():return t.read_until(lambda b:b'qos> ' in b,12)
def cmd(s):
 for c in s.encode()+b'\n':t.write(bytes([c]));time.sleep(.006)
 out=until().decode();print((s[:34]+'...' if len(s)>75 else s),repr(out[-155:]),flush=True)
 assert 'qos> ' in out,out
 return out.split('qos> ',1)[0].splitlines()
def check(s,r):assert r in cmd(s)
def yields():
 rows=cmd('status')
 return int(next(x.split()[-1] for x in rows if re.fullmatch(r'running; yields \d+',x)))
try:
 t.write(b'\n');assert until().endswith(b'qos> ')
 name='apps/spin.sxa'
 data=Path('spin.sxa').read_text()
 rows=cmd('create '+name+' '+data)
 assert 'created '+name in rows or 'already exists' in rows
 check('cat '+name,data)
 check('run '+name,'started');a=yields()
 check('cat notes/spectre.txt','hello from Spectre')
 check('run apps/hello.sxa','run: busy')
 b=yields();assert b>a,(a,b)
 check('stop','stopped');check('status','stopped');check('stop','no running app')
 check('run apps/hello.sxa','started');time.sleep(.1)
 check('status','exit 42')
 check('cat notes/spectre.txt','hello from Spectre')
 check('run '+name,'started');assert yields()>0;check('stop','stopped')
 print('PASS',a,b)
finally:os.close(fd)
