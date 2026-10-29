"""Offline QLOG v3 owner: exclusive inode lock, checked scan, atomic bulk append.

DATA is flushed before one alternate superblock publishes the complete bulk
record. A torn DATA write is uncommitted; a torn seal falls back to the prior
seal. After the commit point a complete new version may be visible even if the
caller was interrupted before receiving success. No committed history is moved.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import fcntl
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from qos_archive import require

PAGE = 4096
NUM = rb'(0|[1-9][0-9]*)'
SEAL = re.compile(rb'QLOG ' + NUM + rb' v3 w' + NUM + rb' c' + NUM + rb' d' + NUM + rb' s' + NUM + rb' m' + NUM + rb' g' + NUM + rb' j' + NUM + rb' x' + NUM + rb'\n')
RECORD = re.compile(rb'(QREC|QDEL|QBLK) ' + NUM + rb' ' + NUM + rb' ([^\s]+)(?: h' + NUM + rb')?\n')
PROFILE_KEY = b'qos/profile'


def checksum(data, seed=7):
    for byte in data:
        seed = (seed * 31 + byte) % 1000000007
    return seed


def line(data):
    end = data.find(b'\n')
    require(end >= 0, "missing QLOG header newline")
    return data[:end + 1]


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

    def page(self):
        prefix = (f'QLOG {self.head} v3 w{self.w} c{self.c} d{self.data_end} '
                  f's{self.swap} m{self.merkle} g{self.generation} j{self.stage}').encode()
        return (prefix + f' x{checksum(prefix) or 1}\n'.encode()).ljust(PAGE, b'\0')


def parse_seal(raw, pages):
    match = SEAL.fullmatch(line(raw))
    require(match is not None, "invalid QLOG v3 superblock")
    values = tuple(map(int, match.groups()))
    meta = Meta(*values[:-1])
    require(meta.page().split(b'\0', 1)[0] == line(raw), "superblock checksum mismatch")
    require(1 <= meta.head <= meta.data_end <= pages - 1 and pages >= 3
            and (meta.data_end <= meta.swap < pages - 1 or meta.swap == meta.data_end == pages - 1)
            and 0 < meta.generation <= 1000000000 and meta.merkle >= 0
            and (meta.w, meta.c) in ((0, 1), (1, 0), (2, 0)), "invalid superblock bounds/flags")
    return meta


def read_exact(fd, offset, size):
    result = bytearray()
    while len(result) < size:
        part = os.pread(fd, size - len(result), offset + len(result))
        require(part, "short disk read")
        result.extend(part)
    return bytes(result)


def write_exact(fd, offset, data):
    while data:
        count = os.pwrite(fd, data, offset)
        require(count > 0, "short disk write")
        offset += count
        data = data[count:]


def flush(fd):
    os.fsync(fd)
    if sys.platform == "darwin":
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)


def metadata(fd):
    size = os.fstat(fd).st_size
    require(size % PAGE == 0 and size >= 3 * PAGE, "invalid disk size")
    pages = size // PAGE
    valid = []
    for at in (0, (pages - 1) * PAGE):
        try:
            valid.append(parse_seal(read_exact(fd, at, PAGE), pages))
        except ValueError:
            pass
    require(valid, "no valid durable QLOG v3 superblock; open/recover legacy disks in QOS first")
    if len(valid) == 2 and valid[0].generation == valid[1].generation:
        require(valid[0] == valid[1], "conflicting superblock generations")
    selected = max(valid, key=lambda meta: meta.generation)
    require((selected.w, selected.c, selected.stage) == (0, 1, 0), "pending disk operation; recover in QOS first")
    return selected


@dataclass(frozen=True)
class Value:
    offset: int
    size: int

    def read(self, fd):
        return read_exact(fd, self.offset, self.size)


def valid_key(key):
    return bool(key) and all(b > 32 and b != 127 for b in key)


def read_line(fd, offset, remaining):
    parts = []
    for begin in range(0, remaining, PAGE):
        part = read_exact(fd, offset + begin, min(PAGE, remaining - begin))
        end = part.find(b'\n')
        if end >= 0:
            return b''.join(parts) + part[:end + 1]
        parts.append(part)
    raise ValueError("bulk frame missing newline")


def scan(fd, meta):
    latest, page = {}, 1
    while page < meta.head:
        header = read_exact(fd, page * PAGE, PAGE)
        match = RECORD.fullmatch(line(header))
        require(match is not None, f"invalid record header at page {page}")
        tag, pages, size, key, expected = match.groups()
        pages, size = int(pages), int(size)
        require(valid_key(key) and pages == (size + PAGE - 1) // PAGE and page + pages + 1 <= meta.head,
                f"record bounds/shape at page {page}")
        start = (page + 1) * PAGE
        h = 7
        for offset in range(0, size, 65536):
            h = checksum(read_exact(fd, start + offset, min(65536, size - offset)), h)
        require(expected is None or int(expected) in (0, h or 1), f"record checksum at page {page}")
        if tag == b'QDEL':
            require(size == 0, "nonempty tombstone")
            latest.pop(key, None)
        elif tag == b'QREC':
            latest[key] = Value(start, size)
        else:
            require(re.fullmatch(NUM, key), "invalid bulk count")
            position = 0
            for _ in range(int(key)):
                require(position < size, "truncated bulk frame")
                prefix = read_line(fd, start + position, size - position)
                fields = prefix[:-1].split(b' ')
                require(len(fields) == 2 and re.fullmatch(NUM, fields[0]) and valid_key(fields[1]), "invalid bulk frame")
                length = int(fields[0])
                position += len(prefix)
                require(length <= size - position, "bulk frame bounds")
                latest[fields[1]] = Value(start + position, length)
                position += length
            require(position == size, "bulk trailing bytes")
        page += pages + 1
    return latest


@contextmanager
def locked(path):
    # Resolve symlinks once; flock also covers hardlinks to this inode. We never
    # replace a live disk inode. The same lock is acquired by blk_raw.c.
    path = Path(path).resolve(strict=True)
    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), "disk must be a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("disk is in use; close QOS before installing or starting another session") from None
        yield fd
    finally:
        os.close(fd)


def bulk_record(items):
    require(items and len({key for key, _ in items}) == len(items), "duplicate/empty bulk keys")
    require(all(valid_key(key) for key, _ in items), "invalid bulk key")
    payload = b''.join(str(len(value)).encode() + b' ' + key + b'\n' + value for key, value in items)
    header = f'QBLK {(len(payload) + PAGE - 1) // PAGE} {len(payload)} {len(items)} h{checksum(payload) or 1}\n'.encode()
    require(len(header) <= PAGE, "bulk header too long")
    return header.ljust(PAGE, b'\0') + payload.ljust((len(payload) + PAGE - 1) // PAGE * PAGE, b'\0')


def append(fd, meta, items, checkpoint=lambda phase, detail: None):
    record = bulk_record(items)
    end = meta.head + len(record) // PAGE
    require(end <= meta.data_end, "disk DATA partition full; compact in QOS or create a larger disk")
    require(meta.generation < 1000000000, "superblock generation exhausted")
    for page in range(len(record) // PAGE):
        write_exact(fd, (meta.head + page) * PAGE, record[page * PAGE:(page + 1) * PAGE])
        checkpoint("data-page", page)
    flush(fd)
    checkpoint("data-flushed", 0)
    updated = replace(meta, head=end, generation=meta.generation + 1)
    seal_at = 0 if updated.generation % 2 == 0 else os.fstat(fd).st_size - PAGE
    # Exactly one publication boundary for archive AND index. The old committed
    # pages and the other valid superblock remain untouched.
    checkpoint("before-seal", seal_at)
    write_exact(fd, seal_at, updated.page())
    checkpoint("seal-written", seal_at)
    flush(fd)
    checkpoint("committed", seal_at)
    return updated


def create(path, size_mib, items):
    path = Path(path).absolute()
    require(size_mib >= 1, "disk size must be at least 1 MiB")
    require(not path.exists() and not path.is_symlink(), "disk already exists; refusing to overwrite")
    # Prepare a private inode and publish by a no-clobber hard link only
    # after the complete seed is flushed. Never expose an empty disk path.
    fd, name = tempfile.mkstemp(prefix='.qos-disk-', dir=path.parent)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pages = size_mib * 1024 * 1024 // PAGE
        os.ftruncate(fd, pages * PAGE)
        end = pages - pages // 8
        record = bulk_record(items)
        head = 1 + len(record) // PAGE
        require(head <= end, "profile does not fit in disk DATA partition")
        write_exact(fd, PAGE, record)
        meta = Meta(head, 0, 1, end, end, 0, 1, 0)
        write_exact(fd, (pages - 1) * PAGE, meta.page())
        write_exact(fd, 0, replace(meta, generation=2).page())
        flush(fd)
        os.link(name, path)  # atomic no-clobber publication, still locked
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.unlink(name)
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(fd)
        if os.path.exists(name):
            os.unlink(name)
