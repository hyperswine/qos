#!/usr/bin/env python3
"""Build a matching Pi Main bundle and seed two hidden reload fixtures.

Run inside the ARM64 Linux SDK VM. No installed image or disk is modified.
"""
import argparse
import os
from pathlib import Path
import platform
import tomllib
ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--output', required=True, type=Path)
ap.add_argument('--cc', required=True)
a = ap.parse_args()
if platform.system() != 'Linux' or platform.machine() != 'aarch64':
    ap.error('requires ARM64 Linux')
# Sol 0.13.1 has no TOML reader. Keep the existing profile grammar at the CLI boundary.
profile = tomllib.loads((ROOT / 'profiles/Main.toml').read_text())
sol = os.environ.get('SOL', 'sol')
os.execvp(sol, [sol, str(ROOT / 'tools/pi4-reliability.sol'),
                str(ROOT), str(a.output.resolve()), a.cc, *profile['apps']])
