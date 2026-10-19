#!/usr/bin/env python3
"""The portable host refuses to make pages r-x outside an image (review I-5).

qosp flips an image's code to r-x with mprotect: the main app image
(Host.loadImage, qos/portable/host.c h_load_image) and a plugin an app
attaches (syscall tag 4, qosp_load_plugin).  The r-x span is the code's
size rounded up to whole pages.  When LOAD claims no writable segment
(rwoff >= memsz) the round-up was unchecked, so it could run past the
image into memory the app owns (its heap, or its own .data), turning it
read-only under its owner.  The host now checks the same spans the native
loader does, and that the r-x pages end inside the image and the arena.

Both legs take a working .qa and rewrite only its LOAD text: memsz =
imagesz (not a page multiple) and rwoff = memsz, so the code's last page
runs past the image.  Each must be refused by name, with no crash; the
untouched archives still load.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ)
ENV.setdefault('FPRISC_ROOT', str(ROOT.parent / 'fprisc'))
PAGE = os.sysconf('SC_PAGE_SIZE')


def run(args, cwd=ROOT, timeout=300, check=True, extra=None):
    p = subprocess.run(list(map(str, args)), cwd=cwd, env={**ENV, **(extra or {})},
                       capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    out = p.stdout + p.stderr
    assert not check or p.returncode == 0, f'{args}: {p.returncode}\n{out[-6000:]}'
    return p.returncode, out


def sections(b):
    head, _, _ = b.partition(b'\n\n')
    base = len(head) + 2
    names = []
    sec = {}
    for line in head.decode().split('\n')[1:]:
        name, off, n = line.split()
        names.append(name)
        sec[name] = b[base + int(off):base + int(off) + int(n)]
    return head.decode().split('\n')[0], names, sec


def with_load(src, dst, edit):
    """Rewrite src's LOAD fields through edit(dict) and re-emit the archive."""
    magic, names, sec = sections(src.read_bytes())
    fields = sec['LOAD'].decode().split()
    load = dict(zip(fields[0::2], fields[1::2]))
    edit(load)
    sec['LOAD'] = ''.join(f'{k} {v}\n' for k, v in load.items()).encode()
    rows, off = [], 0
    for name in names:
        rows.append(f'{name} {off} {len(sec[name])}')
        off += len(sec[name])
    dst.write_bytes(('\n'.join([magic] + rows) + '\n\n').encode() + b''.join(sec[n] for n in names))
    return load


def past_the_image(load):
    size = int(load['imagesz'])
    assert size % PAGE, f'imagesz {size} is a page multiple: the round-up would not run past it'
    load['memsz'] = str(size)
    load['execsz'] = str(size)
    load['rwoff'] = str(size)


with tempfile.TemporaryDirectory(prefix='qos-loader-bounds-') as name:
    tmp = Path(name)
    host = tmp / 'qosp'
    run(['make', '-s', 'portable', f'QOSP_OUT={host}'], cwd=ROOT / 'qos')

    # the main image: Host.loadImage
    good = tmp / 'hello.qa'
    run(['make', '-s', 'qos-app', 'PROG=tests/hello.fpr', f'QA_OUT={good}', f'BUILD={tmp / "hello"}'])
    bad = tmp / 'hello-pastimage.qa'
    with_load(good, bad, past_the_image)
    work = tmp / 'work'
    work.mkdir()
    _, out = run([host, '--yes', good], cwd=work, timeout=60, extra={'FPR_PORT': '0'})
    assert 'fold(1..10)=55' in out, out[-3000:]
    rc, out = run([host, '--yes', bad], cwd=work, timeout=60, check=False, extra={'FPR_PORT': '0'})
    assert rc != 0 and "code pages run past the image" in out and 'fold(' not in out, (rc, out[-3000:])
    assert rc < 128 and 'Segmentation' not in out, (rc, out[-3000:])
    print('loader-bounds main image: r-x pages past the image refused by name, no crash: PASS', flush=True)

    # a plugin: syscall tag 4.  tests/plugbounds.fpr attaches the plugin its
    # kv store holds (a replay returns the record's bytes as they are)
    plug = tmp / 'plugmini.qa'
    run(['make', '-s', 'plugin-qa', 'PROG=tests/plugmini.fpr', f'PLUG_OUT={plug}', f'BUILD={tmp / "plug"}'])
    badplug = tmp / 'plugmini-pastimage.qa'
    with_load(plug, badplug, past_the_image)
    app = tmp / 'plugbounds.qa'
    run(['make', '-s', 'qos-app', 'PROG=tests/plugbounds.fpr', f'QA_OUT={app}', f'BUILD={tmp / "plugbounds"}'])
    for which, archive, want in (('good', plug, r'plugbounds: attached; 40\+2=42'),
                                 ('bad', badplug, r'plugbounds: refused: .*code pages run past the image')):
        pwork = tmp / f'work-{which}'
        (pwork / 'qos-store').mkdir(parents=True)
        data = archive.read_bytes()
        (pwork / 'qos-store' / 'plugbounds.kv').write_bytes(b'%d\n' % len(data) + data + b'\n')
        rc, out = run([host, '--yes', app], cwd=pwork, timeout=60, check=False, extra={'FPR_PORT': '0'})
        assert re.search(want, out) and 'Segmentation' not in out, (which, rc, out[-3000:])
    print('loader-bounds plugin: r-x pages past the image refused by name; the untouched plugin attaches: PASS', flush=True)
print('loader-bounds: PASS')
