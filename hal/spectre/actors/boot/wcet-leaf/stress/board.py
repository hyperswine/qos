import hashlib
import os
import re
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(os.environ['SIMPLE_RISC']) / 'boards/tangnano20k'))
from run_program import open_port
from rom_protocol import FdTransport

image = Path('leaf.sxa').read_text()
name = 'apps/wcet-' + hashlib.sha256(image.encode()).hexdigest()[:8] + '.sxa'
fd = open_port(os.environ.get('SPECTRE_UART', '/dev/cu.usbserial-20250303171'), round(54e6/868))
uart = FdTransport(fd)
def command(line):
    for b in (line+'\n').encode():
        uart.write(bytes([b]))
        time.sleep(.006)
    return uart.read_until(lambda x:b'qos> ' in x, 15)

try:
    uart.write(b'\x03')
    boot = uart.read_until(lambda x:b'qos> ' in x, 20)
    assert b'Spectre SD boot OK' in boot,boot
    created = command('create '+name+' '+image)
    assert b'already exists' in created or ('created '+name).encode() in created,created
    assert image.encode() in command('cat '+name)
    out = command('run '+name)
    out += uart.read_until(lambda x: (out+x).count(b"W ")>=2160 and (out+x).endswith(b"\n"), 90)
    out += command('status 1')
    print(out.decode(), flush=True)
    assert b'exit 42' in out
    rows = re.findall(rb'W ([a-f0-9]{8}) ([a-f0-9]{8}) ([a-f0-9]{8})',out)
    assert len(rows)==2160, len(rows)
    for i,(cycles,insns,start) in enumerate(rows):
        assert int(insns,16)==12,(i,insns)
finally:
    os.close(fd)
