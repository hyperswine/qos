#!/usr/bin/env python3
"""Verify STAR64's post-build login placement with and without QOS autostart."""
import os
from pathlib import Path
import subprocess
import tempfile
HERE=Path(__file__).resolve().parent
script=HERE/'board/qosp/star64/post-build.sh'
with tempfile.TemporaryDirectory(prefix='star64-console-') as temporary:
    root=Path(temporary)
    target=root/'target'; host=root/'host'; images=root/'images'
    (target/'etc/init.d').mkdir(parents=True); (host/'bin').mkdir(parents=True); images.mkdir()
    for name,text in [('spl_tool','#!/bin/sh\nexit 0\n'),('mkimage','#!/bin/sh\nfor last do :; done\n: > "$last"\n')]:
        p=host/'bin'/name;p.write_text(text);p.chmod(0o755)
    table=target/'etc/inittab'
    table.write_text('ttyS0::respawn:/sbin/getty -L ttyS0 0 vt100\n')
    env=dict(os.environ,TARGET_DIR=str(target),HOST_DIR=str(host),BINARIES_DIR=str(images),QOSP_STAR64_AUTHORIZED_KEYS='')
    def build(expected=0):
        p=subprocess.run(['sh',str(script)],env=env,capture_output=True,text=True)
        assert p.returncode==expected,p.stdout+p.stderr
        return p
    build(); assert 'tty1::respawn:' in table.read_text()
    init=target/'etc/init.d/S99qosp';init.write_text('#!/bin/sh\n');init.chmod(0o755)
    build(); build()
    text=table.read_text()
    assert text.count('STAR64_HDMI_LOGIN')==1 and 'tty2::respawn:' in text and 'tty1::' not in text
    assert 'ttyS0::respawn:' in text
    with table.open('a') as f:f.write('tty1::respawn:/sbin/getty tty1\n')
    assert 'custom tty1 getty' in build(1).stderr
print('STAR64 console: tty1 baseline, tty2 with QOS, idempotent rebuild and conflicting getty refusal PASS')
