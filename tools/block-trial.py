#!/usr/bin/env python3
"""Run matched RV64 QEMU block-service trials against the release pin."""
import argparse
import os
import random
import re
import resource
import subprocess
import time
from pathlib import Path

from mkdisk import PG, chunk_hash
from replay_profile import PROFILE_QLOG, replay_kernel

ROOT = Path(__file__).resolve().parents[1]


def seed(path, count, layout, mode):
    events = [f"{i:07d}\n".encode() for i in range(count)]
    pages = []
    def record(tag, key, payload):
        np = (len(payload) + PG - 1) // PG
        pages.append(f"{tag} {np} {len(payload)} {key} h{chunk_hash(payload)}\n".encode())
        pages.extend(payload[i:i + PG] for i in range(0, len(payload), PG))
    record("QREC", "mode", mode.encode())
    record("QREC", "expected", b"".join(events))
    if layout == "mixed":
        # Two packed records, the first spanning two pages. Its unrelated
        # chunk forces both a page boundary and filtering by stream name.
        half = count // 2
        filler = b"x" * PG
        first = b"4096 other\n" + filler
        first += b"".join(b"8 events\n" + event for event in events[:half])
        record("QBLK", str(half + 1), first)
        record("QBLK", str(count - half), b"".join(b"8 events\n" + event for event in events[half:]))
    elif layout == "packed":
        record("QBLK", str(count), b"".join(b"8 events\n" + event for event in events))
    else:
        for event in events:
            record("QREC", "events", event)
    with path.open("wb") as f:
        f.truncate(PG * 4096)
        f.write(f"QLOG {len(pages)+1} v2 w0 c1 d3584 s3584 m0\n".encode())
        for i, data in enumerate(pages, 1):
            f.seek(i * PG)
            f.write(data)


def build(out, env, timing_only):
    base = replay_kernel(ROOT, out).parent
    block = base / "profileblock.fpr"
    s = block.read_text().replace("(from, id, q) = keep borrowed;",
        "_ = Sys.ownerReceived borrowed;\n        (from, id, q) = keep borrowed;")
    block.write_text(s + "\nSys.ownerReceived : (Int, Int, Request) -> Unit .\n")
    qlog = base / "profileqlog.fpr"
    s = qlog.read_text().replace('result = idxReplayE dev idx url "";',
        'result = if Sys.trialReuse Unit == 1 then cachedReplay dev idx url "" (0 - 1) "" else idxReplayE dev idx url "";')
    cached = """
Sys.trialReuse : Unit -> Int .
cachedReplay dev idx url acc prev payload = case idx of
    Nil -> acc
  | e :: rest ->
      Ent key page pl off len = e;
      case strEq key url of
        False -> cachedReplay dev rest url acc prev payload
      | True ->
          data = if page == prev then payload else timedPayload dev page pl;
          joined = strcat acc (substr data off len);
          cachedReplay dev rest url joined page data.
"""
    if timing_only:
        s = (ROOT / f".fpr/store/{PROFILE_QLOG}.fpr").read_text()
        baseline = 'Wire.reply replyTo (Ok (idxReplayE dev idx url ""))'
        variant = 'Wire.reply replyTo (Ok (if Sys.trialReuse Unit == 1 then cachedReplay dev idx url "" (0 - 1) "" else idxReplayE dev idx url ""))'
        if s.count(baseline) != 1:
            raise ValueError("cannot identify replay entry")
        s = s.replace(baseline, variant)
        cached = cached.replace("timedPayload dev page pl", "readPayload dev page pl")
    qlog.write_text(s + cached)
    actors = (Path(env["FPRISC_ROOT"]) / "runtime/actors.c").read_text()
    publish = "      __atomic_store_n(&c->rt, rt + 1, __ATOMIC_RELEASE); /* publish */"
    if actors.count(publish) != 1:
        raise ValueError("cannot locate mailbox publication")
    actors = actors.replace(publish, "      qos_trial_publish(key, m);\n" + publish)
    instrumented = out / "actors.c"
    instrumented.write_text('#include "fpr.h"\nvoid qos_trial_publish(uw key, V m);\n' + actors)
    kernel = base / "trial.fpr"
    source = (ROOT / "tools/fixtures/block-trial.fpr.in").read_text()
    if timing_only:
        source = re.sub(r' \{Sys.replayMetric i \d+\}', '', source)
    kernel.write_text(source)
    extra = [] if timing_only else [f"ACTORS_SRC={instrumented}"]
    flags = "-DQOS_POLL_TRIAL" if timing_only else "-DQOS_POLL_TRIAL -DQOS_REPLAY_BLK_PROFILE"
    image = out / "trial.elf"
    with (out / "build.log").open("w") as log:
        subprocess.run(["make", "-s", "-C", "qos", "native", "HARTS=1",
            f"SYSTEM={kernel}", f"BUILD={out}/build", f"KERNEL={image}",
            *extra, f"NATIVE_TEST_SRC={ROOT}/tests/storewait_replay.c",
            f"NATIVE_CFLAGS_EXTRA={flags}"],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    return image


def boot(out, image, n, layout, mode, repeat, timing_only):
    name = f"{n}-{layout}-{mode}-{repeat}"
    disk = out / "trial.img"
    seed(disk, n, layout, mode)
    cmd = ["qemu-system-riscv64", "-machine", "virt", "-smp", "1", "-m", "256M",
           "-nographic", "-bios", "none", "-kernel", str(image), "-drive",
           f"file={disk},if=none,format=raw,id=hd0", "-device", "virtio-blk-device,drive=hd0"]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    with (out / f"{name}.log").open("w") as log:
        subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                       timeout=90, check=True)
    wall = time.monotonic() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
    log = (out / f"{name}.log").read_text()
    rows = [list(map(int,r.split())) for r in re.findall(r"^trial ([0-9 ]+)",log,re.M)]
    if len(rows) != 16 or "block-trial DONE" not in log or "PANIC" in log:
        raise ValueError(f"incomplete {name}")
    if timing_only:
        if any(len(row) != 3 or row[0] != i for i, row in enumerate(rows)):
            raise ValueError(f"incomplete timing-only samples in {name}")
        return rows, wall, cpu
    unique = {"single": n, "packed": 1, "mixed": 3}[layout]
    expected_reads = unique if mode == "reuse" else (n + n // 2 if layout == "mixed" else n)
    for i,(seq,ticks,beats,reads,distinct,polls,parked,pre,queued,handled,leg) in enumerate(rows):
        if (seq != i or reads != expected_reads or
            distinct != unique or pre + queued + handled != leg):
            raise ValueError(f"invalid {name} sample {i}: {rows[i]}")
    return rows, wall, cpu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--timing-only", action="store_true", help="run without per-read or mailbox probes")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):
        parser.error("output directory must be empty")
    env = dict(os.environ)
    env.setdefault("FPRISC_ROOT",str(ROOT.parent/"fprisc"))
    env.setdefault("XDG_CACHE_HOME",str(out/"cache"))
    image = build(out, env, args.timing_only)
    arms = [(n,layout,mode) for n in (16,128) for layout,mode in
            (("single","200"),("single","100"),("single","50"),("packed","200"),("packed","reuse"))]
    if not args.timing_only:
        for mode in ("200", "reuse"):
            boot(out, image, 128, "mixed", mode, "verify", False)
    rng = random.Random(20261112)
    with (out/"samples.txt").open("w") as raw:
        columns = "" if args.timing_only else "reads distinct polls parked_ticks pre_publish mailbox owner_processing relay_total "
        raw.write("records layout mode boot seq ticks beats " + columns + "boot_wall_s boot_cpu_s\n")
        for repeat in range(3):
            rng.shuffle(arms)
            for n,layout,mode in arms:
                rows,wall,cpu=boot(out,image,n,layout,mode,repeat,args.timing_only)
                for row in rows:
                    print(n,layout,mode,repeat,*row,round(wall,6),round(cpu,6),file=raw)
                raw.flush()
                print(n,layout,mode,repeat,"PASS",flush=True)


if __name__ == "__main__":
    main()
