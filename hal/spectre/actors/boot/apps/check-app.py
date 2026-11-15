import sys,time,os
from pathlib import Path
sys.path.insert(0,str(Path(os.environ['SIMPLE_RISC'])/'boards/tangnano20k'))
from run_program import open_port
import rom_protocol as rom
port=os.environ.get('SPECTRE_UART','/dev/cu.usbserial-20250303171')
fd=open_port(port,round(54e6/868));t=rom.FdTransport(fd)
def until():return t.read_until(lambda b:b'qos> ' in b,18)
def cmd(s):
 for c in s.encode()+b'\n':t.write(bytes([c]));time.sleep(.005)
 r=until().decode();assert r.startswith(s+'\n') and r.endswith('qos> '),repr(r)
 lines=r[len(s)+1:-5].splitlines()
 print(s.split(' ',2)[:2],lines,flush=True);return lines
name='apps/hello.sxa'
try:
 t.write(b'\n');assert until().endswith(b'qos> ')
 image=Path('hello.sxa').read_text()
 r=cmd('create '+name+' '+image)
 assert r in (['created '+name],['already exists'])
 assert cmd('cat '+name)==[image]
 assert name in cmd('ls')
 for i in range(2):assert cmd('run '+name)==['hello from a separately compiled FP-RISC app','exit 42']
 assert cmd('run notes/spectre.txt')==['run: invalid app or exit status']
 assert cmd('cat notes/spectre.txt')==['hello from Spectre']
 # CPU reset -> autonomous SD boot, no install and no image upload.
 t.write(b'\x03');r=until();print(r,flush=True)
 assert b'Spectre SD boot OK' in r and r.endswith(b'qos> ')
 assert cmd('run '+name)==['hello from a separately compiled FP-RISC app','exit 42']
 assert cmd('cat notes/spectre.txt')==['hello from Spectre']
finally:os.close(fd)
