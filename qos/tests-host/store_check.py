#!/usr/bin/env python3
"""Fresh-process compatibility store framing, repair and ACK-failure tests."""
import os
import subprocess
import sys
from pathlib import Path

EXE, ROOT = Path(sys.argv[1]), Path(sys.argv[2])


def call(folder, tag, pay=b'', cap=4096, env=None):
    folder.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([str(EXE), str(tag), pay.hex(), str(cap)], cwd=folder,
                       env={**os.environ, **(env or {})}, capture_output=True,
                       text=True, timeout=10)
    assert p.returncode == 0, (p.returncode, p.stdout, p.stderr)
    rc, text = p.stdout.rstrip('\n').split(' ', 1)
    rc = int(rc)
    return rc, bytes.fromhex(text) if rc >= 0 else text, p.stderr


def record(pay):
    return str(len(pay)).encode() + b'\n' + pay + b'\n'


def seed(folder, data):
    (folder / 'qos-store').mkdir(parents=True, exist_ok=True)
    path = folder / 'qos-store/probe.kv'
    path.write_bytes(data)
    return path


def index(payloads):
    off = 0
    lines = []
    for seq, pay in enumerate(payloads):
        head = len(str(len(pay))) + 1
        lines.append(f'{seq} {off + head} {len(pay)}\n'.encode())
        off += head + len(pay) + 1
    return b''.join(lines)


fresh = ROOT / 'fresh'
assert call(fresh, 3)[:2] == (0, b'')
assert call(fresh, 5)[:2] == (0, b'')
assert not (fresh / 'qos-store').exists()
payloads = [b'A\0B\nZ', b'', b'second']
rc, _, trace = call(fresh, 2, payloads[0], env={'QOS_STORE_TEST_TRACE': '1'})
assert rc == 0 and trace == 'FDPfdp', (rc, trace)
for pay in payloads[1:]:
    assert call(fresh, 2, pay)[0] == 0
assert (fresh / 'qos-store/probe.kv').read_bytes() == b''.join(map(record, payloads))
assert call(fresh, 3)[:2] == (11, b''.join(payloads))
want = index(payloads)
assert call(fresh, 5)[:2] == (len(want), want)
assert call(fresh, 3, cap=11)[:2] == (11, b''.join(payloads))
first_index = index(payloads[:1])
for tag, cap in [(3, 7), (3, 0), (5, len(first_index)), (5, 0), (5, len(want) - 1)]:
    rc, why, _ = call(fresh, tag, cap=cap)
    assert rc == -1, (tag, cap, rc, why)
assert (fresh / 'qos-store/probe.kv').read_bytes() == b''.join(map(record, payloads))
print('store: fresh-process binary/empty append, replay/index overflow refusal and file/store-dir/parent flush order: PASS')

base = record(b'old')
for number, tail in enumerate([b'1', b'10\npar', b'3\nnew', b'0\n']):
    folder = ROOT / f'torn-{number}'
    path = seed(folder, base + tail)
    assert call(folder, 3)[:2] == (3, b'old')
    want = index([b'old'])
    assert call(folder, 5)[:2] == (len(want), want)
    assert path.read_bytes() == base + tail
    assert call(folder, 2, b'fresh')[0] == 0
    assert path.read_bytes() == base + record(b'fresh')
    assert call(folder, 3)[:2] == (8, b'oldfresh')
    want = index([b'old', b'fresh'])
    assert call(folder, 5)[:2] == (len(want), want)
print('store: truncated final header/payload/delimiter excluded from replay/index and repaired before later append: PASS')

for number, bad in enumerate([b'garbage', b'3x\nbad\n', b'-1\nx\n', b'01\nx\n',
                              b'18446744073709551615\n', b'3\nbadX']):
    folder = ROOT / f'malformed-{number}'
    original = base + bad + record(b'new')
    path = seed(folder, original)
    # Even a capacity-limited request validates the remainder of the log.
    for tag, cap in [(3, 4096), (3, 0), (5, 4096), (5, 0), (2, 4096)]:
        assert call(folder, tag, b'next', cap)[0] == -1
        assert path.read_bytes() == original
print('store: malformed interior/overflow/delimiter refuses replay/index/append without discarding later records: PASS')

new = b'partial-record'
for cut in range(len(record(new))):
    folder = ROOT / f'write-cut-{cut}'
    path = seed(folder, base)
    rc, why, _ = call(folder, 2, new, env={'QOS_STORE_TEST_WRITE_LIMIT': str(cut)})
    assert rc == -5 and 'outcome unknown' in why, (cut, rc, why)
    assert path.read_bytes() == base + record(new)[:cut]
    assert call(folder, 3)[:2] == (3, b'old')
    assert call(folder, 2, b'later')[0] == 0
    assert path.read_bytes() == base + record(b'later')
    assert call(folder, 3)[:2] == (8, b'oldlater')
    want = index([b'old', b'later'])
    assert call(folder, 5)[:2] == (len(want), want)
print('store: every partial write boundary returns unknown; fresh-process repair never strands a later acknowledged record: PASS')

for kind in ['SYNC', 'CLOSE']:
    for ordinal in range(1, 4):
        folder = ROOT / f'{kind.lower()}-{ordinal}'
        path = seed(folder, base)
        rc, why, _ = call(folder, 2, b'new', env={f'QOS_STORE_TEST_FAIL_{kind}_AT': str(ordinal)})
        assert rc == -5 and 'outcome unknown' in why, (kind, ordinal, rc, why)
        # Full bytes may have landed despite a failed barrier/close. Never
        # retry that operation automatically: the failed outcome is uncertain.
        assert call(folder, 3)[:2] == (6, b'oldnew')
        assert call(folder, 2, b'later')[0] == 0
        assert path.read_bytes() == base + record(b'new') + record(b'later')
print('store: file/directory/parent flush and close errors report uncertain outcome, never success: PASS')

folder = ROOT / 'eintr'
path = seed(folder, base)
assert call(folder, 2, b'new', env={'QOS_STORE_TEST_EINTR_READ': '1',
                                  'QOS_STORE_TEST_EINTR_WRITE': '1',
                                  'QOS_STORE_TEST_EINTR_SYNC': '1'})[0] == 0
assert path.read_bytes() == base + record(b'new')
folder = ROOT / 'bad-length'
assert call(folder, 2, env={'QOS_STORE_TEST_INVALID_LENGTH': '1'})[0] == -1
assert not (folder / 'qos-store').exists()
folder = ROOT / 'bad-directory'
folder.mkdir(parents=True)
(folder / 'qos-store').write_bytes(b'not a directory')
assert call(folder, 2, b'new')[0] == -5
assert call(folder, 3)[0] == -1
assert (folder / 'qos-store').read_bytes() == b'not a directory'
p = subprocess.run([str(EXE), 'lock'], cwd=ROOT / 'fresh', capture_output=True,
                   text=True, timeout=5)
assert p.returncode == 0 and p.stdout == '-1 11\n', (p.stdout, p.stderr)
print('store: EINTR retry, invalid length/directory refusal, invalid-plugin request unlock: PASS')
print('store-check: PASS (fresh processes and injected faults; physical power cuts untested)')
