#!/usr/bin/env python3
"""Portable Qlog barriers and fresh-process crash-state recovery.

Snapshots model interrupted writes and corrupt metadata deterministically.
These are process/format tests, not physical power-cut or SD-card qualification.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PG, NP, D, PRIME = 4096, 64, 56, 1000000007
ENV = {**os.environ, 'XDG_CACHE_HOME': '/tmp/qos-durable-cache'}


def run(args, cwd=ROOT, env=None, timeout=300):
    p = subprocess.run([str(a) for a in args], cwd=cwd,
                       env={**ENV, **(env or {})}, capture_output=True,
                       text=True, timeout=timeout)
    assert p.returncode == 0, f'{args}: {p.returncode}\n{p.stdout}{p.stderr}'
    return p.stdout + p.stderr


def hh(data):
    acc = 7
    for b in data:
        acc = (acc * 31 + b) % PRIME
    return acc or 1


def combine(a, b):
    return ((a * 1000003) % PRIME + b + 17) % PRIME or 1


def page(data):
    assert len(data) <= PG
    return data.ljust(PG, b'\0')


def put(img, p, data):
    img[p * PG:(p + 1) * PG] = page(data)


def seal(head, gen, *, w=0, c=1, stage=0, root=0, d=D):
    prefix = f'QLOG {head} v3 w{w} c{c} d{d} s{d} m{root} g{gen} j{stage}'.encode()
    return prefix + f' x{hh(prefix)}\n'.encode()


def slots(img, head, g=10, **kwargs):
    put(img, 0, seal(head, g, **kwargs))
    put(img, NP - 1, seal(head, g + 1, **kwargs))


def seeded(legacy=None):
    img = bytearray(PG * NP)
    # The dead record precedes key, so partial compaction changes DATA.
    put(img, 1, f'QREC 1 4 dead h{hh(b"gone")}\n'.encode())
    put(img, 2, b'gone')
    put(img, 3, f'QREC 1 3 key h{hh(b"old")}\n'.encode())
    put(img, 4, b'old')
    put(img, 5, f'QDEL 0 0 dead h{hh(b"")}\n'.encode())
    if legacy == 1:
        put(img, 0, b'QLOG 6\n')
    elif legacy == 2:
        put(img, 0, f'QLOG 6 v2 w0 c1 d{D} s{D} m0\n'.encode())
    else:
        slots(img, 6)
    return img


def valid_stable_slots(img, head):
    for p in (0, NP - 1):
        line = bytes(img[p * PG:(p + 1) * PG]).split(b'\n', 1)[0]
        prefix, check = line.rsplit(b' x', 1)
        assert int(check) == hh(prefix), line
        assert re.match(fr'QLOG {head} v3 w0 c1 '.encode(), line), line


def main():
    with tempfile.TemporaryDirectory(prefix='qos-durable-') as td:
        tmp = Path(td)
        host = tmp / 'host'
        run(['make', '-s', 'portable', f'QOSP_OUT={host}',
             'FPRBUILD_EXTRA=--cflag -DQOS_BLK_TEST'], cwd=ROOT / 'qos')
        fixture = (ROOT / 'tests/portabledurable.fpr').read_text()
        fixture = fixture.replace('../programs/mods/qlog', str(ROOT / 'programs/mods/qlog'))
        apps = {}
        for action in (0, 1, 2, 3, 4, 5, 6):
            src = tmp / f'probe-{action}.fpr'
            src.write_text(fixture.replace('action = 0.', f'action = {action}.'))
            apps[action] = tmp / f'probe-{action}.qa'
            run(['make', '-s', 'qos-app', f'PROG={src}', f'BUILD={tmp}/build-{action}',
                 f'QA_OUT={apps[action]}'])

        def probe(name, img, action=0, env=None):
            disk = tmp / f'{name}.disk'
            disk.write_bytes(img)
            out = run([host, '--yes', apps[action]], cwd=tmp,
                      env={'FPR_DISK': str(disk), 'FPR_HARTS': '2', **(env or {})}, timeout=40)
            return out, bytearray(disk.read_bytes())

        def has(out, want):
            assert want in out, out

        out, fresh = probe('fresh', bytes(PG * NP))
        has(out, 'Ok head=1 v=3 w=0 c=1')
        valid_stable_slots(fresh, 1)
        out, _ = probe('fresh-reboot', fresh)
        has(out, 'Ok head=1 v=3')
        out, _ = probe('fresh-tiny', bytes(PG * 8))
        has(out, 'Ok head=1 v=3 w=0 c=1 data=7 swap=7')
        out, _ = probe('fresh-8mb', bytes(8 * 1024 * 1024))
        has(out, 'Ok head=1 v=3 w=0 c=1 data=1792 swap=1792')
        for ver in (1, 2):
            out, migrated = probe(f'migrate-v{ver}', seeded(ver))
            has(out, 'Ok head=6 v=3')
            has(out, 'key=Ok old dead=Err no such file')
            valid_stable_slots(migrated, 6)
        dirty_legacy = seeded(2)
        put(dirty_legacy, 0, f'QLOG 6 v2 w1 c0 d{D} s{D} m0\n'.encode())
        out, migrated = probe('migrate-v2-interrupted-append', dirty_legacy)
        has(out, 'Ok head=6 v=3 w=0 c=1')
        valid_stable_slots(migrated, 6)
        print('Portable durable: blank format, fresh-process reopen, v1/v2 bounded migration: PASS', flush=True)

        for name, img in [('bad-metadata', bytearray(PG * NP)),
                          ('erased-metadata-live-data', seeded())]:
            if name == 'bad-metadata':
                put(img, 0, b'not a Qlog superblock')
            else:
                put(img, 0, b'')
                put(img, NP - 1, b'')
            out, after = probe(name, img)
            has(out, 'Err dead actor')
            assert after == img, name
        full_legacy = bytearray(PG * NP)
        put(full_legacy, 0, f'QLOG {NP}\n'.encode())
        out, after = probe('migration-no-room', full_legacy)
        has(out, 'Err dead actor')
        assert after == full_legacy
        for name, fields in [('unknown-flags', f'w9 c7 d{D} s{D}'),
                             ('invalid-flags', f'w0 c0 d{D} s{D}'),
                             ('swap-past-end', f'w0 c1 d{D} s999999'),
                             ('swap-before-start', f'w0 c1 d{D} s{D - 1}'),
                             ('negative-merkle', f'w0 c1 d{D} s{D}'),
                             ('unsafe-legacy-compaction', f'w2 c0 d{D} s{D}')]:
            invalid = seeded(2)
            merkle = -1 if name == 'negative-merkle' else 0
            put(invalid, 0, f'QLOG 6 v2 {fields} m{merkle}\n'.encode())
            out, after = probe(f'legacy-{name}', invalid)
            has(out, 'Err dead actor')
            assert after == invalid, name
        print('Portable durable: invalid/nonblank metadata and unsafe migration refuse without mutation: PASS', flush=True)

        out, appended = probe('append', seeded(), 1)
        has(out, 'Ok append head=8 v=3')
        has(out, 'key=Ok new')
        out, _ = probe('append-reboot', appended)
        has(out, 'Ok head=8 v=3')
        for corrupt, want in [(0, 6), (NP - 1, 8)]:
            damaged = bytearray(appended)
            damaged[corrupt * PG] ^= 1
            out, repaired = probe(f'one-bad-{corrupt}', damaged)
            has(out, f'Ok head={want} v=3')
        both = bytearray(appended)
        both[0] ^= 1
        both[(NP - 1) * PG] ^= 1
        out, after = probe('both-bad', both)
        has(out, 'Err dead actor')
        assert after == both
        bad_checksum = seeded()
        for p in (0, NP - 1):
            off = p * PG + bytes(bad_checksum[p * PG:(p + 1) * PG]).index(b' m0') + 2
            bad_checksum[off] = ord('1')
        out, after = probe('bad-checksum', bad_checksum)
        has(out, 'Err dead actor')
        assert after == bad_checksum
        exhausted = seeded()
        put(exhausted, 0, seal(6, 1000000000))
        put(exhausted, NP - 1, seal(6, 999999999))
        for action in (1, 2):
            out, after = probe(f'generation-exhausted-{action}', exhausted, action)
            has(out, 'Ok refused superblock generation exhausted')
            assert after == exhausted
        print('Portable durable: append survives reopen, newest valid slot wins, corrupt slots refused/repaired: PASS', flush=True)

        out, swapped = probe('swap-reserves-backup', seeded(), 3)
        has(out, f'Ok swap first={NP - 2} second={D}')
        valid_stable_slots(swapped, 6)
        assert swapped[(NP - 2) * PG:].startswith(b'swap-end')
        assert swapped[D * PG:].startswith(b'swap-wrap')
        print('Portable durable: SWAP wraps before the backup superblock: PASS', flush=True)

        out, after = probe('stale-heads', seeded(), 4)
        has(out, 'stale-append=Err stale log head stale-compact=Err stale log head verify=Ok verified 3 records')
        assert after == seeded()
        corruptions = []
        bad_header = seeded()
        put(bad_header, 1, b'invalid header before a later valid key record\n')
        corruptions.append(('invalid-header', bad_header, 'invalid record header at page 1'))
        bad_bounds = seeded()
        put(bad_bounds, 3, f'QREC 4 3 key h{hh(b"old")}\n'.encode())
        corruptions.append(('record-bounds', bad_bounds, 'invalid record bounds at page 3'))
        bad_shape = seeded()
        put(bad_shape, 3, f'QREC 2 3 key h{hh(b"old")}\n'.encode())
        corruptions.append(('record-shape', bad_shape, 'invalid record shape at page 3'))
        bad_hash = seeded()
        put(bad_hash, 4, b'BAD')
        corruptions.append(('payload-hash', bad_hash, 'hash mismatch at page 3'))
        bad_bulk = seeded()
        pay = b'50 key\nx'
        put(bad_bulk, 3, f'QBLK 1 {len(pay)} 1 h{hh(pay)}\n'.encode())
        put(bad_bulk, 4, pay)
        corruptions.append(('bulk-framing', bad_bulk, 'invalid bulk framing at page 3'))
        for name, img, why in corruptions:
            out, after = probe(f'compact-{name}', img, 2)
            has(out, f'Ok refused {why}')
            assert after == img, name
            out, after = probe(f'startup-{name}', img, 5)
            has(out, 'Err dead actor')
            assert after == img, name
        valid_bulk = seeded()
        pay = b'3 key\nold'
        put(valid_bulk, 3, f'QBLK 1 {len(pay)} 1 h{hh(pay)}\n'.encode())
        put(valid_bulk, 4, pay)
        out, _ = probe('valid-bulk', valid_bulk, 4)
        has(out, 'verify=Ok verified 3 records')
        out, _ = probe('valid-bulk-startup', valid_bulk, 5)
        has(out, 'durable: Ok Ok head=6')
        print('Portable durable: stale heads refuse without mutation; invalid header/bounds/shape/hash/bulk refuse compact and actor startup: PASS', flush=True)

        out, after = probe('invalid-append-inputs', seeded(), 6)
        has(out, 'input tag=True empty=True space=True newline=True tab=True nul=True oversize=True tombstone=True bulk=True count=True bulk-key=True')
        assert after == seeded()
        out, _ = probe('invalid-inputs-reopen', after, 5)
        has(out, 'durable: Ok Ok head=6')
        print('Portable durable: invalid tags/keys/header size/tombstone/bulk inputs refuse without mutation and valid image reopens: PASS', flush=True)

        # An actual large .qa-style QREC, ending partway through its last
        # page, verifies without building one concatenated payload String.
        large = bytearray(8 * 1024 * 1024)
        payload = (bytes(range(256)) * (PG * 512 // 256))[:-13]
        head = 514
        put(large, 0, seal(head, 10, d=1792))
        put(large, 2047, seal(head, 11, d=1792))
        put(large, 1, f'QREC 512 {len(payload)} apps/large.qa h{hh(payload)}\n'.encode())
        large[2 * PG:2 * PG + len(payload)] = payload
        out, _ = probe('streamed-large-record', large, 5)
        has(out, 'durable: Ok Ok head=514')
        damaged = bytearray(large)
        damaged[2 * PG + len(payload) - 1] ^= 1
        out, after = probe('streamed-large-record-corrupt', damaged, 5)
        has(out, 'Err dead actor')
        assert after == damaged
        print('Portable durable: streamed ~2MiB QREC startup verifies partial last page and catches its final payload byte corruption: PASS', flush=True)

        # No ACK on either data-barrier or metadata-barrier error. The latter
        # may leave old or new metadata: a failed commit has uncertain outcome.
        for ordinal in (2, 3):
            out, failed = probe(f'append-flush-{ordinal}', seeded(), 1,
                                {'QOS_BLK_TEST_FAIL_FLUSH_AT': str(ordinal)})
            has(out, 'Err dead actor')
            assert 'Ok append' not in out, out
            out, _ = probe(f'append-failed-reopen-{ordinal}', failed)
            has(out, f'Ok head={6 if ordinal == 2 else 8} v=3')
        print('Portable durable: injected data/commit flush failures end owner without success ACK: PASS', flush=True)

        original = seeded()
        kept = [bytes(original[3 * PG:4 * PG]), bytes(original[4 * PG:5 * PG])]
        stage = 7
        for pg in kept:
            stage = combine(stage, hh(pg))
        staged = bytearray(original)
        for i, pg in enumerate(kept):
            put(staged, D + i, pg)
        out, _ = probe('stage-before-prepare', staged)
        has(out, 'Ok head=6 v=3')
        prepared = bytearray(staged)
        slots(prepared, 3, g=12, w=2, c=0, stage=stage, root=hh(b'old'))
        for copied in (0, 1, 2):
            cut = bytearray(prepared)
            for i in range(copied):
                put(cut, 1 + i, kept[i])
            out, recovered = probe(f'compact-cut-{copied}', cut)
            has(out, 'Ok head=3 v=3 w=0 c=1')
            has(out, 'key=Ok old dead=Err no such file')
            valid_stable_slots(recovered, 3)
            out, _ = probe(f'compact-cut-reboot-{copied}', recovered)
            has(out, 'Ok head=3 v=3')
        first_stable = bytearray(prepared)
        for i, pg in enumerate(kept):
            put(first_stable, 1 + i, pg)
        put(first_stable, 0, seal(3, 14, root=hh(b'old')))
        out, recovered = probe('compact-first-final-slot', first_stable)
        has(out, 'Ok head=3 v=3')
        valid_stable_slots(recovered, 3)
        damaged = bytearray(prepared)
        damaged[D * PG] ^= 1
        out, after = probe('bad-stage', damaged)
        has(out, 'Err dead actor')
        assert after == damaged
        print('Portable durable: staged, partial-copy, full-copy and first-final-slot snapshots recover; bad stage refused: PASS', flush=True)

        out, compacted = probe('compact', original, 2)
        has(out, 'Ok compact head=3 v=3')
        valid_stable_slots(compacted, 3)
        out, twice = probe('compact-again', compacted, 2)
        has(out, 'Ok compact head=3 v=3')
        valid_stable_slots(twice, 3)
        crowded = seeded()
        slots(crowded, 6, d=NP - 2)
        out, after = probe('compact-too-large', crowded, 2)
        has(out, 'Ok refused compaction staging partition too small')
        assert after == crowded
        for ordinal in range(2, 8):
            out, failed = probe(f'compact-flush-{ordinal}', original, 2,
                                {'QOS_BLK_TEST_FAIL_FLUSH_AT': str(ordinal)})
            has(out, 'Err dead actor')
            assert 'Ok compact' not in out, out
            out, recovered = probe(f'compact-failed-reopen-{ordinal}', failed)
            has(out, f'Ok head={6 if ordinal == 2 else 3} v=3')
            has(out, 'key=Ok old dead=Err no such file')
            if ordinal != 2:
                valid_stable_slots(recovered, 3)
        print('Portable durable: real compaction/idempotence, pre-mutation capacity refusal, all six flush failure boundaries: PASS', flush=True)
        print('Portable durability checks: PASS (simulated crash snapshots; physical power cuts untested)', flush=True)


if __name__ == '__main__':
    main()
