import ctypes as c
import ctypes.util
from pathlib import Path
d=Path('fs.bin').read_bytes();z=c.CDLL(c.util.find_library('lz4') or '/opt/homebrew/opt/lz4/lib/liblz4.dylib')
b=c.create_string_buffer(z.LZ4_compressBound(len(d)))
n=z.LZ4_compress_default(d,b,len(d),len(b))
if n<=0 or len(d)>2**21: raise ValueError('invalid input or compression failure')
Path('packed.lz4').write_bytes(b.raw[:n])
