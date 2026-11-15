from pathlib import Path
import struct,zlib
d=Path('packed.bin').read_bytes()
if not 0<len(d)<=2097152:raise ValueError('boot slot length')
Path('media.bin').write_bytes(struct.pack('<III',0x31544253,len(d),zlib.crc32(d)).ljust(512,b'\0')+d+b'\0'*(-len(d)%512))
