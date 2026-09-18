#!/usr/bin/env python3
"""Connect this QOS checkout to an independently owned FP-RISC checkout."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / 'fprisc.lock.json'


def dependency():
    if (ROOT / '.installed').is_file():
        return ROOT / 'toolchain'
    value = os.environ.get('FPRISC_ROOT')
    if not value:
        raise ValueError('set FPRISC_ROOT to your fprisc checkout')
    return Path(value).expanduser().resolve()


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def check_release():
    dep = dependency()
    pin = json.loads(LOCK.read_text())['revision']
    if git(dep, 'status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('fprisc has uncommitted changes; commit them, then run ./configure.py --pin')
    if git(dep, 'rev-parse', 'HEAD') != pin:
        raise ValueError('fprisc revision differs from fprisc.lock.json; run ./configure.py --pin and commit the updated lock')
    return pin


def configure(dep, check=False):
    """Validate the dependency without writing anything to either checkout."""
    for name in ('Makefile', 'compiler/Main.hs', 'hal/core/runtime.c', 'core/prelude.fpr'):
        if not (dep / name).is_file():
            raise ValueError(f'{dep} is not a complete fprisc checkout (missing {name})')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true', help='validate FPRISC_ROOT (no files generated)')
    ap.add_argument('--pin', action='store_true', help='record the current clean FP-RISC commit for releases')
    ap.add_argument('--release-check', action='store_true', help='require a clean FP-RISC checkout at the pinned revision')
    a = ap.parse_args()
    dep = dependency()
    configure(dep)
    if a.pin:
        if git(dep, 'status', '--porcelain', '--untracked-files=normal'):
            raise ValueError('commit the fprisc changes before pinning')
        LOCK.write_text(json.dumps({'repository': 'fprisc', 'revision': git(dep, 'rev-parse', 'HEAD'), 'layout': 1}, indent=2) + '\n')
    if a.release_check:
        check_release()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        sys.exit(f'configure: {e}')
