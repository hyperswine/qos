"""mkdisk.py -- seed a QLOG disk image with the built .qa apps.

The apps are SEPARATE from System.qa's image: each apps/<Id>.qa is
written as its own QLOG record at url `apps/<Id>.qa`, plus one
`apps/index` record (newline-separated ids) for discovery.  System.qa
boots, scans the log, lists apps from the index, and reads each .qa
off the disk ON DEMAND at launch -- the same storage protocols the kv
streams use, just different urls.  The rodata registry remains only as
the diskless fallback.

Format (mods/qlog.fpr, docs/DISK.txt -- the v2 grammar; a v1 reader
still finds head as the second word and the url as the fourth):
  page 0:  "QLOG <head> v2 w0 c1 d<dataEnd> s<dataEnd> m0\n"
           (METADATA: head, version, write/commit flags, the DATA
           partition bound, the SWAP cursor, the merkle root)
  record:  header page "QREC <npages> <paylen> <url> h<hash>\n"
           + payload pages, where h is qlog's chunk hash (the
           31-polynomial mod 1e9+7 fold below, pinned nonzero)

usage: mkdisk.py <disk.img> <size_mb> <app1.qa> [app2.qa ...]
"""
import os, sys

PG = 4096
HP = 1000000007


def chunk_hash(payload: bytes) -> int:
    h = 7
    for b in payload:
        h = (h * 31 + b) % HP
    return h or 1


def main():
    img, size_mb, qas = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    pages = []

    def record(url, payload: bytes):
        np = (len(payload) + PG - 1) // PG
        pages.append(f"QREC {np} {len(payload)} {url} h{chunk_hash(payload)}\n"
                     .encode())
        for i in range(np):
            pages.append(payload[i * PG:(i + 1) * PG])

    ids = []
    for qa in qas:
        app_id = os.path.splitext(os.path.basename(qa))[0]
        ids.append(app_id)
        with open(qa, "rb") as f:
            record(f"apps/{app_id}.qa", f.read())
    record("apps/index", ("\n".join(ids) + "\n").encode())

    head = 1 + len(pages)
    npages = size_mb * 1024 * 1024 // PG
    # the last 1/8th of the pages is the SWAP partition (mods/qlog's
    # fmtDataEnd); DATA is bounded at dataEnd, so the seed must fit
    data_end = npages - npages // 8 if npages >= 16 else 0
    if data_end and head > data_end:
        sys.exit(f"mkdisk: {head} pages of seed exceed the DATA "
                 f"partition ({data_end} of {npages} pages)")
    out = bytearray(npages * PG)
    sb = f"QLOG {head} v2 w0 c1 d{data_end} s{data_end} m0\n".encode()
    out[0:len(sb)] = sb
    for i, p in enumerate(pages):
        off = (1 + i) * PG
        out[off:off + len(p)] = p
    with open(img, "wb") as f:
        f.write(out)
    print(f"mkdisk: {img} seeded with {len(ids)} apps "
          f"[{', '.join(ids)}] + apps/index (head={head}, "
          f"data-end={data_end}/{npages})")


if __name__ == "__main__":
    main()
