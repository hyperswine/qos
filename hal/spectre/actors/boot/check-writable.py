import sys,os,time,secrets,json
from pathlib import Path
sys.path.insert(0,str(Path(os.environ.get('SIMPLE_RISC',str(Path.home()/'Documents/GitHub/simple-risc')))/'boards/tangnano20k'))
from run_program import open_port
import rom_protocol as rom
port=Path(os.environ.get('SPECTRE_UART','/dev/cu.usbserial-20250303171'))
cold=sys.argv[1]=='cold'
if cold:
 deadline=time.monotonic()+600
 def waitfor(exists):
  while port.exists()!=exists:
   if time.monotonic()>deadline:raise TimeoutError('USB transition')
   time.sleep(.1)
 assert port.exists(), 'connect board before arming'
 print('armed',flush=True);waitfor(False);print('disconnected',flush=True);waitfor(True)
 print('reconnected',flush=True)
 name,body=json.loads(Path('created-file.json').read_text())
else:
 token=secrets.token_hex(4);name='notes/prompt-'+token+'.txt';body='written at the Spectre prompt '+token
fd=open_port(str(port),round(54e6/868));t=rom.FdTransport(fd)
def prompt():return t.read_until(lambda b:b'qos> ' in b,15)
def cmd(s):
 for ch in s.encode()+b'\n':
  t.write(bytes([ch]));time.sleep(.005)
 r=prompt().decode();print(r,flush=True)
 assert r.startswith(s+'\n') and r.endswith('qos> '),repr(r)
 return r[len(s)+1:-5].splitlines()
try:
 if not cold:t.write(b'\n')
 r=prompt()
 if cold:
  print(repr(r),flush=True)
  assert b'Spectre SD boot OK' in r, 'autonomous SD boot marker missing'
 elif not r.endswith(b'qos> '):t.write(b'\n');r=prompt()
 assert r.endswith(b'qos> '),r
 if not cold:
  assert cmd('create '+name+' '+body)==['created '+name]
  assert cmd('create '+name+' overwrite')==['already exists']
  Path('created-file.json').write_text(json.dumps([name,body]))
 names=cmd('ls');assert name in names and 'notes/spectre.txt' in names
 assert cmd('cat '+name)==[body]
 assert cmd('cat notes/spectre.txt')==['hello from Spectre']
finally:os.close(fd)
