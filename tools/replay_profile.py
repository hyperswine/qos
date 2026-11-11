"""Build a test-only copy of the pinned Qlog with timed replay spans."""
from pathlib import Path
import re
from statistics import median


def replay_kernel(root: Path, out: Path):
    src = out / "profile-src"
    src.mkdir()
    # Keep the original import layout for nativeimage and Qlog dependencies.
    (src / "programs").symlink_to(root / "programs", target_is_directory=True)
    bench = src / "tests"
    bench.mkdir()
    (bench / "nativeimage.fpr").symlink_to(root / "tests/nativeimage.fpr")

    qlog = (root / ".fpr/store/7022992c8e4a9fba.fpr").read_text()
    read = "True -> idxReplayE dev r url (strcat acc (entRead dev e))"
    reply = 'Wire.reply replyTo (Ok (idxReplayE dev idx url ""))'
    if qlog.count(read) != 1 or qlog.count(reply) != 1:
        raise ValueError("expected indexed replay sites in pinned Qlog")
    qlog = qlog.replace(read, """True ->
      begin = Sys.mtime Unit;
      payload = entRead dev e;
      middle = Sys.mtime Unit;
      joined = strcat acc payload;
      end = Sys.mtime Unit;
      _ = Sys.replayRecordCost (middle - begin) (end - middle);
      idxReplayE dev r url joined""")
    qlog = qlog.replace(reply, 'Wire.reply replyTo (Ok (profileReplay dev idx url))')
    qlog += """
Sys.mtime : Unit -> Int .
Sys.replayRecordCost : Int -> Int -> Unit .
Sys.replayDone : Int -> Unit .
profileReplay dev idx url =
  begin = Sys.mtime Unit;
  result = idxReplayE dev idx url "";
  end = Sys.mtime Unit;
  _ = Sys.replayDone (end - begin);
  result.
"""
    # Only replay calls the timed copies. Boot-time reads of the process
    # image and other Qlog operations continue using their original functions.
    parts = qlog[qlog.index("rpParts :"):qlog.index("rpGo :")]
    gather = "rpParts dev (p + 1) (left - take) (substr (pageRead dev p) 0 take :: acc)"
    if parts.count(gather) != 1:
        raise ValueError("unexpected pinned payload gather")
    parts = parts.replace(gather, """_ = Sys.replayPageBegin p;
      begin = Sys.mtime Unit;
      page = pageRead dev p;
      end = Sys.mtime Unit;
      _ = Sys.replayPageCost (end - begin);
      rpParts dev (p + 1) (left - take) (substr page 0 take :: acc)""")
    payload = next(line for line in qlog.splitlines() if line.startswith("readPayload dev p pl ="))
    qlog = qlog.replace("payload = entRead dev e;", "payload = timedEntRead dev e;")
    qlog += "\n" + parts.replace("rpParts", "timedParts")
    qlog += "\n" + payload.replace("readPayload", "timedPayload").replace("rpParts", "timedParts")
    qlog += """
Sys.replayPageBegin : Int -> Unit .
Sys.replayPageCost : Int -> Unit .
Sys.replayPayloadCost : Int -> Int -> Unit .
timedEntRead dev e =
  Ent u p pl off len = e;
  begin = Sys.mtime Unit;
  payload = timedPayload dev p pl;
  middle = Sys.mtime Unit;
  slice = substr payload off len;
  end = Sys.mtime Unit;
  _ = Sys.replayPayloadCost (middle - begin) (end - middle);
  slice.
"""
    (bench / "profileqlog.fpr").write_text(qlog)
    kernel = (root / "tests/storewaitnative.fpr").read_text()
    factory = 'FS.serve (device "blk")'
    fs = (root / ".fpr/store/84826bc9e8ddb4b5.fpr").read_text()
    if ('FS = use "std/fs#84826bc9e8ddb4b5"' not in kernel or kernel.count(factory) != 1
            or 'qlog#7022992c8e4a9fba' not in fs or 'serve dev = Wire.spawn 8 Wire.inboxBytes (QL.actor dev).' not in fs):
        raise ValueError("test kernel no longer uses the expected pinned storage actor")
    kernel = kernel.replace(factory, 'Wire.spawn 8 Wire.inboxBytes (QL.actor (device "blk"))')
    kernel = kernel.replace("runBench =", '''QL = use "profileqlog".
Wire = use "std/storage#a8f7ee14e1efae76".
Sys.replayMetric : Int -> Int -> Int .
dump i = if i == 128 then Unit else
  _ = print "replayprofile {i} {Sys.replayMetric i 0} {Sys.replayMetric i 1} {Sys.replayMetric i 2} {Sys.replayMetric i 3}";
  _ = print "entprofile {i} {Sys.replayMetric i 4} {Sys.replayMetric i 5} {Sys.replayMetric i 6} {Sys.replayMetric i 7}";
  _ = print "blkprofile {i} {Sys.replayMetric i 8} {Sys.replayMetric i 9} {Sys.replayMetric i 10} {Sys.replayMetric i 11}";
  dump (i + 1).
runBench =''').replace("main = runBench.", "main = r = runBench; _ = dump 0; r.")
    path = bench / "profilekernel.fpr"
    path.write_text(kernel)
    return path


def write_report(out: Path):
    """Retain the exact-size, per-boot spans along with their controls."""
    lines = [
        "Native Qlog indexed replay, guest mtime at 10 MHz. Times below are elapsed guest time.",
        "Three fresh QEMU boots per configuration and hart count, 128 eight-byte appends and validated replays each.",
        "Read includes entRead, page access, internal payload assembly and extraction; concat times the outer strcat only.",
        "Page times pageRead; assembly = inclusive readPayload minus pageRead (includes arena, probe overhead and internal assembly).",
        "Inside pageRead, lock = blk_lock(), transfer = blk_rw(page, 0), copy = fpr_mkstr(bdata, PAGE_SZ) including allocation.",
        "Other page ticks include the routed block-service request/reply, worker scheduling, validation, unlock, and probe overhead. All splits are computed per boot before taking medians.",
        "Slice brackets final substr. Unattributed read ticks cover outer entRead bookkeeping and clock/probe overhead.",
        "Actor total brackets idxReplayE before reply construction. Clock and sampling overhead are included.",
        "Control call ticks come from the same ordinal replay on a separate counter-off, unmodified-Qlog boot.",
        "Reproduce: FPRISC_ROOT=<pinned-checkout> python3 tools/store-wait-bench.py --replay-profile <new-directory>",
        "", "Medians across three boots at each exact log length.",
        "harts records lock_ms blk_rw_ms copy_ms other_page_ms page_ms assembly_ms slice_ms other_read_ms read_ms concat_ms actor_ms profiled_call_ms control_call_ms",
    ]
    raw = ["harts run records pages lock_ticks blk_rw_ticks copy_ticks other_page_ticks page_ticks assembly_ticks slice_ticks other_read_ticks read_ticks concat_ticks actor_ticks profiled_call_ticks control_call_ticks"]
    for harts in (1, 2):
        groups = {}
        for run in (1, 2, 3):
            def log(stats):
                return (out / f"{harts}h-stats{stats}-run{run}.log").read_text()
            profiled, control = log(1), log(0)
            rows = re.findall(r"replayprofile (\d+) (\d+) (\d+) (\d+) (\d+)", profiled)
            details = re.findall(r"entprofile (\d+) (\d+) (\d+) (\d+) (\d+)", profiled)
            block = re.findall(r"blkprofile (\d+) (\d+) (\d+) (\d+) (\d+)", profiled)
            pattern = r"storewait ticks \d+ (\d+)"
            on, off = re.findall(pattern, profiled), re.findall(pattern, control)
            if len(block) != 128 or len(details) != 128 or len(rows) != 128 or len(on) != 128 or len(off) != 128:
                raise ValueError("missing replay samples")
            for i, row in enumerate(rows):
                seq, records, reads, concat, elapsed = map(int, row)
                ordinal, pages, page, payload, sliced = map(int, details[i])
                assembly = payload - page
                other = reads - payload - sliced
                if ordinal != i or pages != records or min(assembly, other) < 0:
                    raise ValueError(f"invalid entRead breakdown: {details[i]}")
                block_seq, calls, lock, transfer, copy = map(int, block[i])
                other_page = page - lock - transfer - copy
                if block_seq != seq or calls != pages or other_page < 0:
                    raise ValueError(f"invalid block read breakdown: {block[i]}")
                metrics = (lock, transfer, copy, other_page, page, assembly, sliced, other, reads, concat, elapsed, int(on[i]), int(off[i]))
                if seq != i or records != i + 1 or not reads + concat <= elapsed <= int(on[i]):
                    raise ValueError("invalid replay profile")
                groups.setdefault(records, []).append(metrics)
                raw.append(" ".join(map(str, (harts, run, records, pages, *metrics))))
        for n in (1, 8, 16, 32, 64, 128):
            ms = [median(col) / 10000 for col in zip(*groups[n])]
            lines.append(f"{harts} {n} " + " ".join(f"{v:.3f}" for v in ms))
    (out / "replay-profile.txt").write_text("\n".join([*lines, "", *raw]) + "\n")
