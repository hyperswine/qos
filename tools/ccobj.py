#!/usr/bin/env python3
"""ccobj.py CACHE CC FLAGS... -- SOURCE... : compile each source once.

Prints one object path per source, in order, for a link line to take in
place of the sources.  An image link used to recompile the same runtime
sources three times (the export pass, the image, the moved image), and every
app build did it again: about 14 of a warm build's 24 seconds.

An object's name is the SHA-256 of the compiler's version, the flags and the
source as the preprocessor sees it under those flags (a plain .s file: its
bytes), so a changed header, macro or path is a different object and nothing
is ever reused across them.  Compiled units are assembled once the same way.
An object is written beside its name and renamed whole: builds running at
the same time find it complete or absent.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import subprocess
import sys


def fail(why):
    sys.stderr.write(f'ccobj: {why}\n')
    sys.exit(1)


def main():
    args = sys.argv[1:]
    if '--' not in args or len(args) < 4:
        fail('usage: ccobj.py CACHE CC FLAGS... -- SOURCE...')
    split = args.index('--')
    cache, cc, sources = Path(args[0]), args[1:split], args[split + 1:]
    cache.mkdir(parents=True, exist_ok=True)
    version = subprocess.run([cc[0], '--version'], capture_output=True, check=True).stdout

    def one(source):
        if source.endswith('.s'):
            # plain assembly is not preprocessed: its bytes are all of it
            seen = Path(source).read_bytes()
        else:
            pre = subprocess.run(cc + ['-E', source], capture_output=True)
            if pre.returncode:
                sys.stderr.buffer.write(pre.stderr)
                fail(f'preprocessing {source} failed')
            seen = pre.stdout
        digest = hashlib.sha256()
        for part in (version, '\0'.join(cc).encode(), seen):
            digest.update(hashlib.sha256(part).digest())
        obj = cache / f'{Path(source).stem}-{digest.hexdigest()[:32]}.o'
        if not obj.exists():
            partial = obj.with_name(f'{obj.name}.{os.getpid()}.tmp')
            done = subprocess.run(cc + ['-c', source, '-o', str(partial)], capture_output=True)
            sys.stderr.buffer.write(done.stderr)
            if done.returncode:
                partial.unlink(missing_ok=True)
                fail(f'compiling {source} failed')
            partial.replace(obj)
        return str(obj)

    with ThreadPoolExecutor(max_workers=min(8, len(sources))) as pool:
        print(' '.join(pool.map(one, sources)))


if __name__ == '__main__':
    main()
