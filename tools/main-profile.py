#!/usr/bin/env python3
"""Build and optionally run the Main graphical profile with onboard .qa apps.

    python3 tools/main-profile.py --run

The initial disk is seeded once. Later builds preserve it; use a new output
directory to try a fresh onboard app set. Artifacts can also be installed by
the Buildroot Main Profile option.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def build(output, arch=None, cc=None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    profile = tomllib.loads((ROOT / 'profiles/Main.toml').read_text())
    env = dict(os.environ, XDG_CACHE_HOME=str(output / 'cache'))
    make_vars = ([f'APP_HOST={arch}'] if arch else []) + ([f'QOS_RV64_CC={cc}'] if cc else [])

    def run(*args):
        subprocess.run(list(map(str, args)), cwd=ROOT, env=env, check=True)

    archives = []
    for source in profile['apps']:
        name = Path(source).stem
        archive = output / (name + '.qa')
        run('make', '-s', 'plugin-qa', *make_vars, f'PROG={source}',
            f'PLUG_OUT={archive}', f'BUILD={output / ("plugin-" + name)}')
        archives.append(archive)
    run('make', '-s', 'qos-app', *make_vars, f'PROG={profile["entry"]}',
        f'QA_OUT={output / "main.qa"}', f'BUILD={output / "shell-build"}')
    disk = output / 'Main.disk'
    if not disk.exists():
        run('python3', 'tools/mkdisk.py', disk, 32, *archives)
    else:
        print(f'Preserving existing onboard disk: {disk}', flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/profiles/Main')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--arch', choices=['rv64'], help='cross-build RV64 Linux application images')
    parser.add_argument('--cc', help='RV64 cross compiler for --arch=rv64')
    args = parser.parse_args()
    if args.cc and args.arch != 'rv64':
        parser.error('--cc requires --arch=rv64')
    if args.run and args.arch == 'rv64' and os.uname().machine != 'riscv64':
        parser.error('RV64 images must run on a riscv64 host; build without --run and transfer them')
    output = build(args.output, args.arch, args.cc)
    print(f'Main Profile: {output / "main.qa"}', flush=True)
    if args.run:
        env = dict(os.environ, XDG_CACHE_HOME=str(output / 'cache'),
                   FPR_DISK=str(output / 'Main.disk'))
        subprocess.run(['make', '-s', '-C', 'qos', 'portable-gl'],
                       cwd=ROOT, env=env, check=True)
        os.execve(str(ROOT / 'qos/qosp-gl'),
                  ['qosp-gl', '--yes', str(output / 'main.qa')], env)


if __name__ == '__main__':
    main()
