#!/usr/bin/env python3
"""Package a verified, clean staged macOS ARM64 SDK and generate its Brew formula.

This contributor tool never publishes, rebuilds, or reads user disks. Run the
installed SDK acceptance before publication. The tarball is the release unit:
compiler, SDK, hosts and Main are pinned together in sdk.json and the inventory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob('*'))
            if p.is_file() and p.name != 'files.sha256.json'}


def package(prefix, version, output, compiler_licenses):
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-rc\d+)?', version):
        raise ValueError('version must be MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-rcN')
    sdk = prefix / 'libexec/qos-portable'
    meta = json.loads((sdk / 'sdk.json').read_text())
    revision = subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', ROOT, 'status', '--porcelain'], text=True):
        raise ValueError('commit QOS packaging changes before making a release')
    if meta['qosRevision'] != revision:
        raise ValueError('stage and packager must use the same QOS revision')
    if not (compiler_licenses / 'manifest.json').is_file():
        raise ValueError('compiler license inventory is required')
    notices = json.loads((compiler_licenses / 'manifest.json').read_text())['notices']
    for relative, sha in notices.items():
        notice = (compiler_licenses / relative).resolve()
        if not notice.is_relative_to(compiler_licenses) or digest(notice) != sha:
            raise ValueError('compiler license inventory mismatch')
    if meta['qosDirty'] or meta['fpriscDirty']:
        raise ValueError('release SDK must be staged from clean committed repositories')
    if (meta['os'], meta['architecture']) != ('darwin', 'aarch64'):
        raise ValueError('release packaging is currently qualified only for macOS ARM64')
    recorded = json.loads((sdk / 'files.sha256.json').read_text())
    if inventory(sdk) != recorded:
        raise ValueError('staged SDK inventory mismatch')
    if not meta.get('profileFiles') or not meta.get('runtimeFiles'):
        raise ValueError('release must include Main profile and both hosts')
    # 0.2.0+: the package exports only `qos`; `fpr` belongs to the FP-RISC formula.
    if (prefix / 'bin/fpr').exists() or (prefix / 'bin/fpr').is_symlink():
        raise ValueError('stage exports bin/fpr; restage with this tree (only bin/qos is exported)')
    for path in sdk.rglob('*'):
        if path.suffix in ('.disk', '.hs', '.c') or path.name == '.git':
            raise ValueError(f'unexpected release file: {path}')
    # Do not advertise older systems than the binaries actually target.
    minos = []
    libraries = {}
    for relative in ('compiler/fpr', 'runtime/qosp', 'runtime/qosp-gl'):
        binary = sdk / relative
        load = subprocess.check_output(['vtool', '-show-build', binary], text=True)
        minos.append(re.search(r'\bminos\s+(\S+)', load)[1])
        libraries[relative] = subprocess.check_output(['otool', '-L', binary], text=True).splitlines()[1:]
    minimum = max(minos, key=lambda s: tuple(map(int, s.split('.'))))
    if minimum.split('.')[0] != '27':
        raise ValueError('review formula minimum macOS before packaging binaries for another OS version')
    if output.exists():
        raise ValueError('output must be a fresh directory')
    output.mkdir(parents=True)
    name = f'qos-portable-{version}-macos-arm64'
    with tempfile.TemporaryDirectory(prefix='qos-release-') as temporary:
        bundle = Path(temporary) / name
        shutil.copytree(prefix, bundle, symlinks=True)
        # Staged acceptance makes the input read-only. Only the private copy is writable.
        for p in bundle.rglob('*'):
            if not p.is_symlink():
                p.chmod(p.stat().st_mode | 0o200)
        copied = bundle / 'libexec/qos-portable'
        meta.update(release=version, minimumMacOS=minimum, nativeLibraries=libraries)
        (copied / 'sdk.json').write_text(json.dumps(meta, indent=2) + '\n')
        licenses = copied / 'licenses'
        shutil.copytree(compiler_licenses, licenses)
        shutil.copy2(ROOT / 'LICENSE', licenses / 'QOS-LICENSE')
        # The compiler's license is passed through with the staged inputs.
        if not (copied / 'compiler/LICENSE').is_file():
            raise ValueError('stage must include the FP-RISC license')
        (copied / 'files.sha256.json').write_text(json.dumps(inventory(copied), indent=2) + '\n')
        archive = output / (name + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(bundle, arcname=name)
    sha = digest(archive)
    (output / 'SHA256SUMS').write_text(f'{sha}  {archive.name}\n')
    (output / 'release.json').write_text(json.dumps(meta, indent=2) + '\n')
    template = (ROOT / 'packaging/homebrew/qos-portable.rb.in').read_text()
    formula = template.replace('__VERSION__', version).replace('__ARCHIVE__', archive.name).replace('__SHA256__', sha)
    (output / 'qos-portable.rb').write_text(formula)
    print(archive)
    print(f'SHA256 {sha}')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--compiler-licenses', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        package(args.sdk.resolve(), args.version, args.output.resolve(), args.compiler_licenses.resolve())
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as why:
        parser.exit(1, f'qos release: {why}\n')


if __name__ == '__main__':
    main()
