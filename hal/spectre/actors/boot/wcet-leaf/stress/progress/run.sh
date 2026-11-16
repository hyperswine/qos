#!/usr/bin/env bash
# From any directory: SIMPLE_RISC=... FPRISC=... bash run.sh NEW_OUTPUT
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
leaf=$(cd "$here/../.." && pwd)
board=$(cd "${SIMPLE_RISC:?set SIMPLE_RISC}" && pwd)
compiler=$(cd "${FPRISC:?set FPRISC}" && pwd)/fpr
mkdir "${1:?specify a new output directory}"
cd "$1"
cp "$leaf"/{build.py,leaf.fpr} "$here/../entry.S" .
python3 build.py "$compiler" "$leaf/../apps"
archive="$board/docs/evidence/2026-10-30-structural"
gzip -dc "$archive/generated/observed-cpu.v.gz" > observed.v
tar -xzf "$archive/baseline-sources.tar.gz" sdram/{pipeline_cache,burst_memory,sdram}.v
cp sdram/pipeline_cache.v cache.sv
riscv64-unknown-elf-gcc -march=rv32im -mabi=ilp32 -nostdlib -mno-relax -Ttext=0 "$here/rom.S" -o rom.elf
riscv64-unknown-elf-objcopy -j .text -O binary rom.elf rom.bin
python3 - <<'PY'
import hashlib
import struct
from pathlib import Path
# The monitor uses private counter/predictor signals in this archived top.
for name, expected in {
    'observed.v':'33376ec743baa45d8e117371439636917dc4f9f4201e3ed6e44859b03bbd0e38',
    'leaf.bin':'72dfeb832d1d87c043bef1511202beaf0eb7a90157034159a4a61c43b3393dba',
    'cache.sv':'4bf19aec80fcb87c7b603ffe427af8386472e64425106ef7f1a38ffe478eaf0e',
    'sdram/burst_memory.v':'b96af62e6b1ec957c112d6607d6bfd901560776dedbac9078588cb8910ddb35a',
    'sdram/sdram.v':'fac724ff34098570c5ad55b18fa2fd43770496c11005e8b6992ad27f7830693e'
}.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==expected,name
for source,target in [('rom.bin','rom.hex'),('leaf.bin','image.hex')]:
    words=struct.iter_unpack('<I',Path(source).read_bytes())
    Path(target).write_text(''.join(f'{word:08x}\n' for word, in words))
PY
verilator --binary --timing -j 4 -Wno-fatal --top tb +1364-2005ext+v observed.v cache.sv sdram/{sdram,burst_memory}.v "$here/trace.sv"
python3 "$here/sweep.py"
python3 "$here/analyse.py" > result.json
cat result.json
