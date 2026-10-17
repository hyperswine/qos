"""mkdisk.py -- seed a QLOG disk image with the built .qa apps.

The apps are SEPARATE from System.qa's image: each apps/<Id>.qa is
written as its own QLOG record at url `apps/<Id>.qa`, plus one
`apps/index` record (newline-separated ids) for discovery.  System.qa
boots, scans the log, lists apps from the index, and reads each .qa
off the disk ON DEMAND at launch -- the same storage protocols the kv
streams use, just different urls.  The rodata registry remains only as
the diskless fallback.

Format (mods/qlog.fpr, docs/2026-08-26-DISK.txt -- the v2 grammar; a v1 reader
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


def preserved_pages(img: str, seed_urls: set[str]) -> list[bytes]:
    if not os.path.exists(img):
        return []
    with open(img, "rb") as f:
        raw = f.read()
    if len(raw) < PG or len(raw) % PG != 0:
        return []
    npages = len(raw) // PG
    head = 0
    best_gen = -1
    for slot in (0, npages - 1):
        line = raw[slot * PG:(slot + 1) * PG].split(b"\n", 1)[0].decode("ascii", "replace").split()
        if len(line) >= 2 and line[0] == "QLOG" and line[1].isdigit():
            gen = next((int(w[1:]) for w in line[2:] if w.startswith("g") and w[1:].isdigit()), 0)
            if gen > best_gen:
                best_gen = gen
                head = int(line[1])
    if head <= 1 or head > npages:
        return []
    kept = []
    p = 1
    while p < head:
        hdr = raw[p * PG:(p + 1) * PG].split(b"\n", 1)[0].decode("ascii", "replace").split()
        if len(hdr) < 4 or hdr[0] not in ("QREC", "QDEL", "QBLK") or not hdr[1].isdigit():
            break
        tag, np, url = hdr[0], int(hdr[1]), hdr[3]
        if p + 1 + np > head:
            break
        if not (tag in ("QREC", "QDEL") and url in seed_urls):
            for k in range(1 + np):
                kept.append(raw[(p + k) * PG:(p + k + 1) * PG])
        p += 1 + np
    return kept


def main():
    args = sys.argv[1:]
    preserve = False
    if args and args[0] == "--preserve":
        preserve = True
        args = args[1:]
    img, size_mb, qas = args[0], int(args[1]), args[2:]
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
    if preserve:
        seed_urls = {"apps/index"} | {f"apps/{app_id}.qa" for app_id in ids}
        pages.extend(preserved_pages(img, seed_urls))

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
