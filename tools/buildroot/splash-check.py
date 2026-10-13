#!/usr/bin/env python3
"""Check quiet Pi boot policy and vector rendering without physical devices."""
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
subprocess.run(['python3', str(ROOT / 'tools/boot-logo.py'), '--check'], check=True)
with tempfile.TemporaryDirectory(prefix='qosp-splash-check-') as name:
    work = Path(name)
    binary = work / 'pixels'
    subprocess.run([os.environ.get('CC', 'cc'), '-O2', '-Wall', '-Wextra',
        '-I' + str(ROOT / 'hal/unix'), str(ROOT / 'qos/tests-host/boot_logo_check.c'),
        '-lm', '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    target, images = work / 'target', work / 'images'
    (target / 'etc/init.d').mkdir(parents=True)
    (target / 'usr/bin').mkdir(parents=True)
    (images / 'rpi-firmware').mkdir(parents=True)
    config = work / 'config'
    config.write_text('BR2_PACKAGE_QOSP_AUTOSTART=y\nBR2_PACKAGE_QOSP_BOOT_SPLASH=y\n')
    for p in (target / 'usr/bin/qosp-splash', target / 'etc/init.d/S12qosp-splash'):
        p.write_text('#!/bin/sh\n'); p.chmod(0o755)
    table = target / 'etc/inittab'
    table.write_text('console::respawn:/sbin/getty console\ntty1::respawn:/sbin/getty tty1 # HDMI console\n')
    cmdline = images / 'rpi-firmware/cmdline.txt'
    cmdline.write_text('root=PARTUUID=fixture rootwait console=tty1 console=ttyAMA0,115200 loglevel=7\n')
    env = dict(os.environ, BR2_CONFIG=str(config), BINARIES_DIR=str(images))
    for _ in range(2):
        subprocess.run(['sh', str(HERE / 'board/qosp/rpi4/post-build.sh'), str(target)], env=env, check=True)
    args = cmdline.read_text().split()
    assert 'root=PARTUUID=fixture' in args and 'rootwait' in args
    assert 'console=ttyAMA0,115200' in args and 'console=tty1' not in args
    for flag in ('quiet', 'loglevel=3', 'logo.nologo', 'vt.global_cursor_default=0', 'consoleblank=0'):
        assert args.count(flag) == 1
    assert table.read_text().count('tty2::') == 1 and 'tty1::' not in table.read_text()
    assert 'console::respawn:' in table.read_text()
    assert (target / 'etc/default/qosp').read_text().count('export FPR_BOOT_SPLASH=1') == 1
    (target / 'usr/bin/qosp-splash').unlink()
    result = subprocess.run(['sh', str(HERE / 'board/qosp/rpi4/post-build.sh'), str(target)], env=env, capture_output=True)
    assert result.returncode != 0
print('Splash boot policy: serial/root preserved, HDMI quiet, recovery VT, idempotent build, missing helper refusal PASS')
