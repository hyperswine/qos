#!/usr/bin/env python3
"""Build a private STAR64 PowerVR EGL runtime using the image's Buildroot SDK.

Requires the vendor 1.17.6210866 kernel driver, not the upstream PowerVR driver.
Run on the Linux build machine; this does not install anything on the board.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(out, sdk, jobs):
    spec = json.loads((HERE / 'star64-powervr.json').read_text())
    out.mkdir(parents=True, exist_ok=True)
    saved = out / 'manifest.json'
    if saved.exists() and json.loads(saved.read_text()) != spec:
        raise SystemExit('output contains another manifest; use a fresh directory')
    saved.write_text(json.dumps(spec, indent=2) + '\n')
    host = sdk / 'host'
    cross = sdk / 'build/mesa3d-26.1.8/buildroot-build/cross-compilation.conf'
    if not cross.is_file():
        raise SystemExit('expected the STAR64 Mesa 26.1.8 Buildroot output/SDK')
    env = dict(os.environ, PATH=str(host / 'bin') + ':' + os.environ['PATH'])
    def run(args, **kw):
        kw.setdefault('env', env)
        subprocess.run([str(a) for a in args], check=True, **kw)
    def fetch(url, sha256, dest):
        if not dest.exists() or digest(dest) != sha256:
            temp = dest.with_suffix('.download')
            with urllib.request.urlopen(url, timeout=120) as response, temp.open('wb') as stream:
                shutil.copyfileobj(response, stream)
            if digest(temp) != sha256:
                temp.unlink()
                raise ValueError('checksum mismatch: ' + url)
            temp.replace(dest)
        return dest
    mesa_tar = fetch(**spec['mesa'], dest=out / 'mesa.tar.xz')
    vendor_tar = fetch(**spec['vendor'], dest=out / 'vendor.tar.gz')
    patches = out / 'patches'; patches.mkdir(exist_ok=True)
    def patch_fetch(item):
        return fetch(spec['patch_base'] + item['name'], item['sha256'], patches / item['name'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        patch_files = list(pool.map(patch_fetch, spec['patches']))
    src = out / 'mesa-22.1.3'
    if not (out / 'source-ready').exists():
        if src.exists():
            shutil.rmtree(src)
        with tarfile.open(mesa_tar) as tar:
            tar.extractall(out, filter='data')
        formats = src / 'src/mesa/main/formats.csv'
        formats.write_bytes(formats.read_bytes().replace(b'\r\n', b'\n'))
        for patch in patch_files:
            with patch.open('rb') as stream:
                run(['patch', '-s', '-p1'], cwd=src, stdin=stream)
        # glibc 2.44 exposes once_flag/call_once through stdlib.h. Use that
        # implementation instead of redeclaring Mesa 22's emulated version.
        thread = src / 'include/c11/threads_posix.h'
        text = thread.read_text()
        text = text.replace('#define ONCE_FLAG_INIT PTHREAD_ONCE_INIT',
            '#ifndef ONCE_FLAG_INIT\n#define MESA_EMULATE_ONCE\n#define ONCE_FLAG_INIT PTHREAD_ONCE_INIT\n#endif')
        text = text.replace('typedef pthread_once_t  once_flag;',
            '#ifdef MESA_EMULATE_ONCE\ntypedef pthread_once_t  once_flag;\n#endif')
        before = 'static inline void\ncall_once(once_flag *flag, void (*func)(void))\n{\n    pthread_once(flag, func);\n}'
        if before not in text:
            raise ValueError('unexpected Mesa call_once source')
        thread.write_text(text.replace(before, '#ifdef MESA_EMULATE_ONCE\n' + before + '\n#endif'))
        (out / 'source-ready').touch()
    builddir = out / 'mesa-build'
    if not (builddir / 'build.ninja').exists():
        run([host / 'bin/python3', host / 'bin/meson', 'setup', builddir, src,
            '--cross-file', cross, '--prefix=/usr', '--libdir=lib',
            '-Dbuildtype=release', '-Dgallium-drivers=pvr', '-Dvulkan-drivers=',
            '-Dplatforms=', '-Dglx=disabled', '-Degl=enabled', '-Dgbm=enabled',
            '-Dgles1=disabled', '-Dgles2=enabled', '-Dopengl=true',
            '-Dshared-glapi=enabled', '-Dllvm=disabled', '-Dlibunwind=disabled',
            '-Dlmsensors=disabled', '-Dvalgrind=disabled', '-Ddri3=disabled',
            '-Dgallium-omx=disabled', '-Dgallium-va=disabled',
            '-Dgallium-vdpau=disabled', '-Dgallium-xa=disabled'])
    run(['ninja', '-C', builddir, '-j', jobs])
    bundle = out / 'bundle'
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir()
    run(['ninja', '-C', builddir, 'install'], env=dict(env, DESTDIR=str(bundle / 'mesa')))
    vendor = out / 'vendor-source'; vendor.mkdir(exist_ok=True)
    with tarfile.open(vendor_tar) as tar:
        tar.extractall(vendor, filter='data')
    target = vendor / ('img-gpu-powervr-bin-' + spec['ddk']) / 'target'
    libs = bundle / 'vendor/usr/lib'; libs.mkdir(parents=True)
    for name in ('libpvr_dri_support', 'libsrv_um', 'libglslcompiler', 'libusc',
                 'libufwriter', 'libGLESv2_PVR_MESA', 'libPVRScopeServices'):
        for path in (target / 'usr/lib').glob(name + '.so*'):
            shutil.copy2(path, libs / path.name, follow_symlinks=False)
    shutil.copytree(target / 'lib/firmware', bundle / 'firmware')
    shutil.copy2(target / 'etc/init.d/rc.pvr', bundle / 'vendor/rc.pvr.reference')
    # The source tarball carries Mesa licensing; retain it beside the runtime.
    shutil.copy2(src / 'docs/license.rst', bundle / 'MESA-LICENSE.rst')
    for libdir in (bundle / 'mesa/usr/lib', libs):
        for path in libdir.rglob('*.so*'):
            if path.is_file() and not path.is_symlink():
                run([host / 'bin/riscv64-linux-strip', '--strip-unneeded', path])
    shutil.copy2(saved, bundle / 'manifest.json')
    archive = out / 'bundle.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(bundle, arcname='bundle')
    print(f'{archive}: sha256 {digest(archive)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--buildroot-output', required=True, type=Path)
    parser.add_argument('--jobs', type=int, default=4, choices=range(1, 17))
    args = parser.parse_args()
    build(args.output.resolve(), args.buildroot_output.resolve(), args.jobs)
