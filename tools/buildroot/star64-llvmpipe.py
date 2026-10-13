#!/usr/bin/env python3
"""Build an isolated, checksum-pinned LLVMpipe runtime bundle for STAR64.

Run on a machine with dpkg-deb (no package installation or maintainer scripts).
The bundle is an optional board deployment artifact, not a Buildroot sysroot.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def build(out, manifest, jobs):
    if not shutil.which('dpkg-deb'):
        raise SystemExit('dpkg-deb is required; run this artifact builder on the Linux build machine')
    spec = json.loads(manifest.read_text())
    if spec['format'] != 1 or spec['architecture'] != 'riscv64':
        raise SystemExit('expected a format-1 riscv64 manifest')
    out.mkdir(parents=True, exist_ok=True)
    saved = out / 'manifest.json'
    if saved.exists() and json.loads(saved.read_text()) != spec:
        raise SystemExit('output contains another manifest; use a fresh output directory')
    packages = out / 'packages'; packages.mkdir(exist_ok=True)
    def fetch(item):
        relative = Path(item['Filename'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'pool':
            raise ValueError('invalid Debian package path')
        dest = packages / relative.name
        if not dest.exists() or digest(dest) != item['SHA256']:
            temporary = dest.with_suffix('.download')
            with urllib.request.urlopen(spec['source'] + item['Filename'], timeout=120) as response, temporary.open('wb') as stream:
                shutil.copyfileobj(response, stream)
            if digest(temporary) != item['SHA256']:
                temporary.unlink()
                raise ValueError('checksum mismatch for ' + item['Package'])
            temporary.replace(dest)
        print(item['Package'], item['Version'], 'verified', flush=True)
        return dest
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        paths = list(pool.map(fetch, spec['packages']))
    bundle = out / 'bundle'; bundle.mkdir(exist_ok=True)
    for path in paths:
        subprocess.run(['dpkg-deb', '-x', str(path), str(bundle)], check=True)
    saved.write_text(json.dumps(spec, indent=2) + '\n')
    archive = out / 'bundle.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(bundle, arcname='bundle')
        tar.add(saved, arcname='manifest.json')
    print(f'{archive}: sha256 {digest(archive)}', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--manifest', type=Path, default=HERE / 'star64-llvmpipe.json')
    parser.add_argument('--jobs', type=int, default=4, choices=range(1, 17))
    args = parser.parse_args()
    build(args.output.resolve(), args.manifest, args.jobs)
