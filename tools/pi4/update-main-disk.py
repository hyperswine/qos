#!/usr/bin/env python3
"""Append matching onboard archives to a stopped Main v3 disk snapshot.

Never edits the source or overwrites an output. Requires two valid, stable
superblocks and a verified committed log. Preserve all history; refuse a custom
app index because its additional native archives also need rebuilding together.
Use only while the installed service is stopped, then install with rollback.
"""
import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re

PG = 4096
APPS = ('clock', 'logs', 'browser', 'disk')
NUM = rb'(0|[1-9][0-9]*)'
SEAL = re.compile(rb'QLOG ' + NUM + rb' v3 w' + NUM + rb' c' + NUM +
                  rb' d' + NUM + rb' s' + NUM + rb' m' + NUM +
                  rb' g' + NUM + rb' j' + NUM + rb' x' + NUM + rb'\n')
REC = re.compile(rb'(QREC|QDEL|QBLK) ' + NUM + rb' ' + NUM +
                 rb' ([^\s]+)(?: h' + NUM + rb')?\n')


def check(ok, why):
    if not ok:
        raise ValueError(why)


def digest(data):
    h = 7
    for b in data:
        h = (h * 31 + b) % 1000000007
    return h or 1


def first_line(page):
    end = page.find(b'\n')
    check(end >= 0, 'missing header newline')
    return page[:end + 1]


@dataclass(frozen=True)
class Meta:
    head: int
    w: int
    c: int
    data_end: int
    swap: int
    merkle: int
    generation: int
    stage: int

    def line(self):
        prefix = (f'QLOG {self.head} v3 w{self.w} c{self.c} d{self.data_end} '
                  f's{self.swap} m{self.merkle} g{self.generation} j{self.stage}').encode()
        return prefix + f' x{digest(prefix)}\n'.encode()


def parse_seal(page, pages):
    line = first_line(page)
    match = SEAL.fullmatch(line)
    check(match is not None, 'expected canonical durable v3 superblock')
    values = list(map(int, match.groups()))
    meta = Meta(*values[:-1])
    check(line == meta.line(), 'superblock checksum mismatch')
    check(1 <= meta.head <= meta.data_end <= pages - 1, 'superblock bounds')
    check(meta.data_end <= meta.swap < pages - 1 or
          meta.swap == meta.data_end == pages - 1, 'swap bounds')
    check(0 < meta.generation <= 1000000000, 'generation bounds')
    check((meta.w, meta.c, meta.stage) == (0, 1, 0), 'pending disk operation; recover in QOS first')
    return meta


def valid_key(key):
    return bool(key) and all(b > 32 and b != 127 for b in key)


def scan(data, head):
    """Verify Qlog framing/hash rules, retaining the latest value for each key."""
    data = bytes(data)
    latest, p, count = {}, 1, 0
    while p < head:
        match = REC.fullmatch(first_line(data[p * PG:(p + 1) * PG]))
        check(match is not None, f'invalid record header at page {p}')
        tag, np, size, key, hh = match.groups()
        np, size = int(np), int(size)
        check(valid_key(key), f'invalid key at page {p}')
        check(np == (size + PG - 1) // PG and p + 1 + np <= head,
              f'record bounds/shape at page {p}')
        payload = data[(p + 1) * PG:(p + 1) * PG + size]
        check(hh is None or int(hh) == 0 or int(hh) == digest(payload),
              f'payload checksum at page {p}')
        if tag == b'QDEL':
            check(np == size == 0, 'nonempty tombstone')
            latest.pop(key, None)
        elif tag == b'QREC':
            latest[key] = payload
        else:
            check(re.fullmatch(NUM, key) is not None, 'invalid bulk count')
            pos = 0
            for _ in range(int(key)):
                line = first_line(payload[pos:])
                fields = line[:-1].split(b' ')
                check(len(fields) == 2 and re.fullmatch(NUM, fields[0]) is not None
                      and valid_key(fields[1]), 'invalid bulk frame')
                length = int(fields[0])
                pos += len(line)
                check(length <= len(payload) - pos, 'bulk frame bounds')
                latest[fields[1]] = payload[pos:pos + length]
                pos += length
            check(pos == size, 'bulk payload trailing bytes')
        p += 1 + np
        count += 1
    check(p == head, 'record crosses committed head')
    return latest, count


def prepare(data, archives):
    check(len(data) % PG == 0 and len(data) >= 3 * PG, 'invalid disk size')
    pages = len(data) // PG
    slots = [parse_seal(data[:PG], pages), parse_seal(data[-PG:], pages)]
    check(slots[0].generation != slots[1].generation or slots[0] == slots[1],
          'conflicting superblock generations')
    meta = max(slots, key=lambda x: x.generation)
    check(meta.generation <= 1000000000 - 2, 'generation exhausted')
    latest, count = scan(data, meta.head)
    check(latest.get(b'apps/index') == ''.join(a + '\n' for a in APPS).encode(),
          'custom/missing app index; rebuild every indexed archive before updating')
    check(set(archives) == set(APPS), 'exactly the four onboard archives are required')
    records = bytearray()
    for app in APPS:
        payload = archives[app]
        check(bool(payload), f'empty {app} archive')
        np = (len(payload) + PG - 1) // PG
        line = f'QREC {np} {len(payload)} apps/{app}.qa h{digest(payload)}\n'.encode()
        records.extend(line.ljust(PG, b'\0'))
        records.extend(payload.ljust(np * PG, b'\0'))
    new_head = meta.head + len(records) // PG
    check(new_head <= meta.data_end, 'insufficient DATA space; compact in QOS first')
    out = bytearray(data)
    out[meta.head * PG:new_head * PG] = records
    # Both fallback slots describe the matching bundle; parity follows Qlog.
    for gen in (meta.generation + 1, meta.generation + 2):
        pos = 0 if gen % 2 == 0 else (pages - 1) * PG
        out[pos:pos + PG] = replace(meta, head=new_head, generation=gen).line().ljust(PG, b'\0')
    return out, {'old_head': meta.head, 'new_head': new_head, 'preserved_records': count,
                 'old_generation': meta.generation, 'new_generation': meta.generation + 2,
                 'apps': list(APPS)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('bundle', type=Path, help='directory containing clock.qa, logs.qa, browser.qa, disk.qa')
    args = ap.parse_args()
    try:
        check(args.source.resolve() != args.output.resolve(), 'source and output must differ')
        data, report = prepare(args.source.read_bytes(),
                               {a: (args.bundle / (a + '.qa')).read_bytes() for a in APPS})
        with args.output.open('xb') as f:
            try:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            except BaseException:
                args.output.unlink()
                raise
        print(json.dumps(report, sort_keys=True))
    except (ValueError, OSError) as e:
        ap.exit(1, f'update-main-disk: {e}\n')


if __name__ == '__main__':
    main()
