import os,re,sys,tempfile,hashlib,secrets
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'boards/tangnano20k'))
import rom_protocol as rom
from run_program import open_port
if not __debug__:raise SystemExit("Run without -O: this harness uses assertions")
fd=open_port(sys.argv[3],round(54e6/868))
t=rom.FdTransport(fd)
def ready(prefix=b''):
    out=prefix
    if b'READY\n' not in out:
        out+=t.read_until(lambda b:b'READY\n' in out+b or b'FAIL\n' in out+b,12)
    if not out.endswith(b'READY\n'):raise RuntimeError(out[:150])
    return out
def boot():
    ident=rom.query_identity(fd,expected_mhz=54)
    print(ident.raw,flush=True)
    image=Path(sys.argv[2]).read_bytes()
    rom.check_compatibility(ident,expected_cpu_mhz=54,image_bytes=len(image),required_caps='UICG')
    rom.upload_image_u(fd,image,max_words=ident.max_bytes//4,timeout=45)
    out=ready(rom.start_guarded(fd))
    cid=re.search(rb'CID ([0-9a-f]{32})\n',out)[1]
    return cid
def read():
    t.write(b'R');return bytes.fromhex(re.search(rb'DATA ([0-9a-f]{1024})\n',ready())[1].decode())
def write(data):
    t.write(b'W'+data.hex().encode());assert b'WROTE\n' in ready()
try:
    cid=boot();original=read()
    path=Path(tempfile.mkdtemp(prefix='spectre-sd-',dir='.'))/(cid.decode()+'-131072.bin')
    with path.open('xb') as f:f.write(original);f.flush();os.fsync(f.fileno())
    record=b'QOS/Spectre reset test\n'+secrets.token_bytes(489)
    assert len(record)==512 and original!=record
    print('Backup:',path,'test SHA256:',hashlib.sha256(record).hexdigest(),flush=True)
    write(record);assert read()==record
    print('Write and immediate read OK; resetting CPU to ROM and reloading image',flush=True)
    assert boot()==cid
    after=read()
    write(original);assert read()==original
    print('Original sector restored and verified',flush=True)
    assert after==record
    print('PASS: fresh actor read all 512 bytes after reset',flush=True)
finally:os.close(fd)
