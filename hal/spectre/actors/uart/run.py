"""Usage: python3 run.py SIMPLE_RISC_ROOT uart.bin PORT"""
import sys,os,time
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'boards/tangnano20k'))
import rom_protocol as rom
from run_program import open_port
fd=open_port(sys.argv[3],round(54e6/868))
try:
 t=rom.FdTransport(fd)
 ident=rom.query_identity(fd,expected_mhz=54)
 data=Path(sys.argv[2]).read_bytes()
 rom.check_compatibility(ident,expected_cpu_mhz=54,image_bytes=len(data),required_caps='UICG')
 print(ident.raw,flush=True)
 rom.upload_image_u(fd,data,max_words=ident.max_bytes//4,timeout=45)
 buf=rom.start_guarded(fd)
 for marker,byte in [(b'READY A\n',b'A'),(b'READY B\n',b'Z'),(b'DONE',None)]:
  if marker not in buf:buf+=t.read_until(lambda b:marker in buf+b or b'FAIL' in buf+b,5)
  if marker not in buf:raise RuntimeError(buf)
  if byte:time.sleep(.080);t.write(byte)
 print(buf.decode(),flush=True)
 assert b'2 claims/acks; scheduler ping/pong OK' in buf
finally:os.close(fd)
