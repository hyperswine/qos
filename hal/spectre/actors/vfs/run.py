import sys,os,time
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'boards/tangnano20k'))
import rom_protocol as rom
from run_program import open_port
if len(sys.argv)!=5 or sys.argv[4] not in ('--initialize-test-slice','--read-existing'):
    sys.exit('usage: run.py SIMPLE_RISC image.bin PORT --read-existing|--initialize-test-slice')
image=Path(sys.argv[2]).read_bytes()
fd=open_port(sys.argv[3],round(54e6/868));t=rom.FdTransport(fd)
try:
 for mode in ((b'W',b'R') if sys.argv[4]=='--initialize-test-slice' else (b'R',)):
    ident=rom.query_identity(fd,expected_mhz=54)
    print('ROM',ident.raw,mode,flush=True)
    rom.check_compatibility(ident,expected_cpu_mhz=54,image_bytes=len(image),required_caps='UICG')
    rom.upload_image_u(fd,image,max_words=ident.max_bytes//4,timeout=300,retries=0)
    out=rom.start_guarded(fd)
    if b'MODE?\n' not in out:out+=t.read_until(lambda b:b'MODE?\n' in out+b,8)
    if b'MODE?\n' not in out:raise RuntimeError(out)
    t.write(mode)
    out=t.read_until(lambda b:b'DONE' in b,25)
    print(out.decode(errors='replace'),flush=True)
    expected=b'SAVED ' if mode==b'W' else b'READ hello from Spectre\n'
    if expected.rstrip(b'\n') not in out.splitlines() or not out.endswith(b'DONE'):raise RuntimeError('VFS acceptance failed')
finally:os.close(fd)
