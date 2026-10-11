#!/usr/bin/env python3
"""Exercise qosp.mk's actual target install recipe in synthetic rootfs trees.

Buildroot 2025.02.x's SysV skeleton has a real /var/lib and a misc symlink
inside it. Reject custom volatile ancestor links instead of following them.
This checks package construction, not a booted image or power-loss behavior.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PACKAGE = Path(__file__).resolve().parent / 'package/qosp'
INSTALL = shutil.which('ginstall') or shutil.which('install')
assert INSTALL, 'GNU install is required (coreutils on macOS)'


with tempfile.TemporaryDirectory(prefix='qosp-package-install-') as name:
    temp = Path(name)
    build = temp / 'build'
    build.mkdir()
    for filename in ('qosp', 'qosp-service-guard', 'app.qa'):
        (build / filename).write_text(f'fixture {filename}\n')
    makefile = temp / 'install.mk'
    makefile.write_text(f'''QOSP_PKGDIR := {PACKAGE}
INSTALL := {INSTALL}
include {PACKAGE}/qosp.mk
.PHONY: {build}/install
{build}/install:
\t$(QOSP_INSTALL_TARGET_CMDS)
''')

    def install(root, success=True):
        result = subprocess.run(['make', '-s', '-f', str(makefile),
                                 f'TARGET_DIR={root}', f'QOSP_APP={build}/app.qa', str(build / 'install')],
                                capture_output=True, text=True, timeout=10)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result.stdout + result.stderr

    for name in ('empty', 'normal', 'stock-sysv'):
        root = temp / name
        root.mkdir()
        if name != 'empty':
            (root / 'var/lib').mkdir(parents=True)
        if name == 'stock-sysv':
            # Verified 2025.02.x skeleton: misc, not /var/lib, is volatile.
            (root / 'tmp').mkdir()
            (root / 'var/lib/misc').symlink_to('../../tmp')
            (root / 'var/log').symlink_to('../tmp')
        install(root)
        state = root / 'var/lib/qosp'
        assert state.is_dir() and not any(p.is_symlink() for p in (state, state.parent, state.parent.parent))
        assert (state.stat().st_mode & 0o777) == 0o755
        disk = state / 'qosp.disk'
        disk.write_text('existing writable state')
        install(root)
        assert disk.read_text() == 'existing writable state'
        assert (root / 'usr/bin/qosp-session').is_file()
        if name == 'stock-sysv':
            assert os.readlink(root / 'var/lib/misc') == '../../tmp'
            assert os.readlink(root / 'var/log') == '../tmp'
            assert not (root / 'tmp/qosp').exists()
        print(f'Package install: {name} has a pre-existing real state directory and preserves state HOLDS', flush=True)

    for name in ('var', 'var/lib', 'var/lib/qosp'):
        root = temp / ('linked-' + name.replace('/', '-'))
        (root / 'tmp').mkdir(parents=True)
        link = root / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(os.path.relpath(root / 'tmp', link.parent))
        output = install(root, success=False)
        assert 'default state path must use real directories' in output, output
        assert link.is_symlink() and not (root / 'tmp/qosp').exists()
        assert not (root / 'usr/bin/qosp').exists()
        print(f'Package install: linked /{name} fails before installing into volatile storage HOLDS', flush=True)
