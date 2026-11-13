#!/usr/bin/env python3

"""Build and optionally run the Main graphical profile with onboard .qa apps.

    python3 tools/main-profile.py --run

The initial disk is seeded once. Later builds preserve it; use a new output
directory to try a fresh onboard app set. Artifacts can also be installed by
the Buildroot Main Profile option.

A run starts the host compiler daemon (tools/fprd.py) beside qosp, on a
private socket, so the Editor builds and runs FP-RISC (Sys.compile); it stops
with qosp.  --no-compiler runs without it (the Editor then says so).
"""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
def fprisc_root():
    given = os.environ.get('FPRISC_ROOT', '').strip()
    if not given and (ROOT / 'fprisc.path').exists():
        given = (ROOT / 'fprisc.path').read_text().strip()
    return Path(given or ROOT.parent / 'fprisc').resolve()


def build(output, arch=None, cc=None, force=False):
    """Legacy interactive frontend; all build policy lives in Sol."""
    argv = [os.environ.get('SOL', 'sol'), ROOT / 'tools/main-profile.sol',
            '--root', ROOT, '--fprisc', fprisc_root(), '--output', output.resolve()]
    if arch:
        argv += ['--arch', arch]
    if cc:
        argv += ['--cc', cc]
    if force:
        argv += ['--force']
    env = dict(os.environ, FPR_HOME=str(ROOT), FPR_PATH=str(fprisc_root()))
    subprocess.run(list(map(str, argv)), cwd=ROOT, env=env, check=True)
    return output.resolve()


@contextmanager
def compiler(output):
    """the host compiler daemon on a private socket, for the run's length"""
    with tempfile.TemporaryDirectory(prefix='qos-fprd-', dir='/tmp') as directory:
        sock = str(Path(directory) / 'compiler.sock')
        log = output / 'fprd.log'
        env = dict(os.environ, FPRISC_ROOT=str(fprisc_root()), FPRD_BUILD=str(output / 'fprd'),
                   XDG_CACHE_HOME=str(output / 'cache'))
        with log.open('w') as sink:
            daemon = subprocess.Popen([sys.executable, 'tools/fprd.py', sock], cwd=ROOT, env=env,
                                      stdout=sink, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not Path(sock).exists() and daemon.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if not Path(sock).exists():
                sys.exit('compiler daemon did not start: ' + log.read_text())
            print(f'Compiler daemon: {sock} (log {log})', flush=True)
            yield sock
        finally:
            # the daemon's whole group: a make or compiler it is running too
            try:
                os.killpg(daemon.pid, signal.SIGTERM)
                daemon.wait(timeout=10)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(daemon.pid, signal.SIGKILL)
                daemon.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/profiles/Main')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--force', action='store_true', help='rebuild all .qa archives even when up to date')
    parser.add_argument('--no-compiler', action='store_true', help='run without the host compiler daemon')
    parser.add_argument('--arch', choices=['rv64'], help='cross-build RV64 Linux application images')
    parser.add_argument('--cc', help='RV64 cross compiler for --arch=rv64')
    args = parser.parse_args()
    if args.cc and args.arch != 'rv64':
        parser.error('--cc requires --arch=rv64')
    if args.run and args.arch == 'rv64' and os.uname().machine != 'riscv64':
        parser.error('RV64 images must run on a riscv64 host; build without --run and transfer them')
    output = build(args.output, args.arch, args.cc, force=args.force)
    print(f'Main Profile: {output / "main.qa"}', flush=True)
    if args.run:
        env = dict(os.environ, XDG_CACHE_HOME=str(output / 'cache'),
                   FPR_DISK=str(output / 'Main.disk'))
        subprocess.run(['make', '-s', '-C', 'qos', 'portable-gl'],
                       cwd=ROOT, env=env, check=True)
        command = [str(ROOT / 'qos/qosp-gl'), '--yes', str(output / 'main.qa')]
        if args.no_compiler:
            os.execve(command[0], command, env)
        with compiler(output) as sock:
            code = subprocess.run(command, env=dict(env, FPRD_SOCK=sock)).returncode
        sys.exit(code)


if __name__ == '__main__':
    main()
