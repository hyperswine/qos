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
USE_RE = re.compile(r'\buse\s+"([^"]+)"')


def fprisc_root():
    """dependency.mk's rule: $FPRISC_ROOT, else fprisc.path, else ../fprisc"""
    given = os.environ.get('FPRISC_ROOT', '').strip()
    if not given and (ROOT / 'fprisc.path').exists():
        given = (ROOT / 'fprisc.path').read_text().strip()
    return Path(given or ROOT.parent / 'fprisc').resolve()


def fpr_closure(entry: Path, fprisc: Path) -> set[Path]:
    seen = set()
    stack = [entry.resolve()]
    while stack:
        cur = stack.pop()
        if cur in seen or not cur.is_file():
            continue
        seen.add(cur)
        try:
            text = cur.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for spec in USE_RE.findall(text):
            nm, _, want_hash = spec.partition('#')
            rel = nm if nm.endswith('.fpr') else nm + '.fpr'
            cands = [cur.parent / rel, ROOT / rel, fprisc / rel]
            if want_hash:
                cands.extend([ROOT / '.fpr/store' / f'{want_hash}.fpr',
                              fprisc / '.fpr/store' / f'{want_hash}.fpr'])
            for c in cands:
                if c.is_file():
                    stack.append(c.resolve())
    return seen


def is_fresh(target: Path, deps) -> bool:
    if not target.is_file():
        return False
    t = target.stat().st_mtime
    return all(not d.exists() or t >= d.stat().st_mtime for d in deps)


def build(output, arch=None, cc=None, force=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fprisc = fprisc_root()
    profile_path = ROOT / 'profiles/Main.toml'
    profile = tomllib.loads(profile_path.read_text())
    env = dict(os.environ, XDG_CACHE_HOME=str(output / 'cache'))
    make_vars = ([f'APP_HOST={arch}'] if arch else []) + ([f'QOS_RV64_CC={cc}'] if cc else [])

    def run(*args):
        subprocess.run(list(map(str, args)), cwd=ROOT, env=env, check=True)

    run('make', '-s', 'fpr')
    stamp_file = output / '.target'
    want_stamp = f'{arch or "host"}:{cc or ""}\n'
    if stamp_file.is_file():
        if stamp_file.read_text() != want_stamp:
            force = True
    elif arch or cc:
        force = True

    common_plug = {
        fprisc / 'fpr', fprisc / 'core/prelude.fpr',
        ROOT / 'core/foreign.fpr', ROOT / 'qos-app.mk', ROOT / 'dependency.mk',
        ROOT / 'qos/appside/qos_abi.h', ROOT / 'qos/appside/link-qosplug.ld',
        ROOT / 'qos/appside/link-qosplug-rv64.ld',
        ROOT / 'tools/mkimports.py', ROOT / 'tools/mkqa.py', profile_path,
    }
    common_app = common_plug | {
        ROOT / 'tools/mkexports.py', ROOT / 'loader/qaimg.c', ROOT / 'qos/portable/sha256.c',
        ROOT / 'qos/appside/entry.c', ROOT / 'qos/appside/hal.c', ROOT / 'qos/appside/support.c',
        ROOT / 'qos/appside/link-qosapp.ld', ROOT / 'qos/appside/link-qosapp-a64.ld',
        ROOT / 'qos/appside/link-qosapp-rv64.ld',
        *(fprisc / 'runtime').glob('*.[ch]'), *(fprisc / 'machine/unix').glob('*'),
    }

    archives = []
    rebuilt_plug = False
    for source in profile['apps']:
        name = Path(source).stem
        archive = output / (name + '.qa')
        deps = common_plug | fpr_closure(ROOT / source, fprisc)
        if not force and is_fresh(archive, deps):
            print(f'{archive} is up to date', flush=True)
        else:
            run('make', '-s', 'plugin-qa', *make_vars, f'PROG={source}',
                f'PLUG_OUT={archive}', f'BUILD={output / ("plugin-" + name)}')
            rebuilt_plug = True
        archives.append(archive)

    main_qa = output / 'main.qa'
    main_deps = common_app | fpr_closure(ROOT / profile['entry'], fprisc)
    if not force and is_fresh(main_qa, main_deps):
        print(f'{main_qa} is up to date', flush=True)
    else:
        run('make', '-s', 'qos-app', *make_vars, f'PROG={profile["entry"]}',
            f'QA_OUT={main_qa}', f'BUILD={output / "shell-build"}')

    stamp_file.write_text(want_stamp)
    disk = output / 'Main.disk'
    if not disk.exists():
        run('python3', 'tools/mkdisk.py', disk, 32, *archives)
    elif rebuilt_plug or not is_fresh(disk, archives):
        run('python3', 'tools/mkdisk.py', '--preserve', disk, 32, *archives)
    else:
        print(f'Preserving existing onboard disk: {disk}', flush=True)
    return output


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
