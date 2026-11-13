#!/usr/bin/env python3
"""Measure native app-state calls under QEMU. Pass an empty output directory.
FPRISC_ROOT selects the compiler checkout. Each boot gets a fresh disk.
"""
import argparse
import math
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check_store_records(disk):
    pages = disk.read_bytes()
    records = [offset for offset in range(0, len(pages), 4096)
               if pages.startswith(b"QREC 1 8 apps/CkSlow/CkSlow.kv h", offset)]
    if len(records) != 128 or any(pages[i + 4096:i + 4104] != b"event-1\n" for i in records):
        raise ValueError(f"expected 128 app-scoped event records in {disk.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--replay-profile", action="store_true", help="time record reads and concatenation inside indexed replay")
    modes.add_argument("--reply-trace", action="store_true",
                        help="timestamp mailbox publication and correlated receipt in the instrumented arm")
    modes.add_argument("--files-check", action="store_true",
                       help="check blocking receive through lifecycle-owned Files in one two-hart boot")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        parser.error("output directory must be empty")
    env = dict(os.environ)
    env.setdefault("FPRISC_ROOT", str(ROOT.parent / "fprisc"))
    env.setdefault("XDG_CACHE_HOME", str(out / "cache"))

    def run(command, timeout=300):
        return subprocess.run(list(map(str, command)), cwd=ROOT, env=env, check=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)

    manifest = out / "CkSlow.toml"
    manifest.write_text('name = "CkSlow"\nid = "CkSlow"\nentry = "n/a"\n'
                        'loadMode = "process"\nversion = "1"\n')
    app = out / "CkSlow.qa"
    run([os.environ.get("SOL", "sol"), "tools/build-process-app.sol", "tests/storewaitbench.fpr", manifest, app])
    if args.reply_trace:
        # Compile a temporary copy of the release runtime. Fail on source drift
        # rather than silently observing a different stage of delivery.
        actors = (Path(env["FPRISC_ROOT"]) / "runtime/actors.c").read_text()
        publication = "      __atomic_store_n(&c->rt, rt + 1, __ATOMIC_RELEASE); /* publish */"
        if actors.count(publication) != 1:
            raise ValueError("cannot identify the mailbox publication site")
        actors = actors.replace(publication,
                                "      qos_trace_publish(key, (V)a, m);\n" + publication)
        trace = ROOT / "tests/storewait_trace.c"
        (out / "actors_trace.c").write_text(f'#include "{trace}"\n' + actors)

    if args.replay_profile:
        from replay_profile import replay_kernel, write_report
        profiled_kernel = replay_kernel(ROOT, out)
    for harts in ((2,) if args.files_check else (1, 2)):
        kernels = {}
        for counters in ((1,) if args.files_check else (0, 1)):
            name = f"{harts}h-stats{counters}"
            kernels[counters] = out / f"{name}.elf"
            tracing = args.reply_trace and counters
            kernel_test = "storewaittrace" if tracing else "storewaitnative"
            if args.files_check:
                kernel_test = "storewaitfiles"
            flags = f"-DQOS_STORE_WAIT_STATS={counters}"
            extra = []
            if tracing:
                flags += " -DQOS_STORE_REPLY_TRACE"
                extra.append(f"ACTORS_SRC={out}/actors_trace.c")
            system = ROOT / f"tests/{kernel_test}.fpr"
            if args.replay_profile and counters:
                flags += " -DQOS_REPLAY_BLK_PROFILE"
                system = profiled_kernel
                extra.append(f"NATIVE_TEST_SRC={ROOT}/tests/storewait_replay.c")
            run(["make", "-s", "-C", "qos", "native", f"HARTS={harts}",
                 f"SYSTEM={system}", f"KERNEL={kernels[counters]}",
                 f"BUILD={out}/{name}", f"NATIVE_CFLAGS_EXTRA={flags}", *extra])
        for repeat in range(1 if args.files_check else 3):
            order = (0, 1) if repeat % 2 == 0 else (1, 0)
            for counters in ((1,) if args.files_check else order):
                name = f"{harts}h-stats{counters}-run{repeat + 1}"
                disk = out / f"{name}.img"
                run([os.environ.get("SOL", "sol"), "tools/mkdisk.sol", disk, "16", app])
                command = ["qemu-system-riscv64", "-machine", "virt", "-smp", str(harts),
                           "-m", "256M", "-nographic", "-bios", "none", "-kernel", str(kernels[counters]),
                           "-drive", f"file={disk},if=none,format=raw,id=hd0", "-device", "virtio-blk-device,drive=hd0"]
                with (out / f"{name}.log").open("w") as log:
                    subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, timeout=120, check=True)
                log = (out / f"{name}.log").read_text()
                check_store_records(disk)
                samples = re.findall(r"storewait ticks (\d+) (\d+)", log)
                if len(samples) != 128 or "storewait: DONE" not in log or "PANIC" in log:
                    raise ValueError(f"incomplete workload in {name}.log")
                if args.replay_profile and counters:
                    rows = re.findall(r"replayprofile (\d+) (\d+) (\d+) (\d+) (\d+)", log)
                    if len(rows) != len(samples):
                        raise ValueError(f"missing actor samples in {name}")
                    for i, row in enumerate(rows):
                        seq, records, reads, concat, elapsed = map(int, row)
                        if (seq != i or records != i + 1 or reads + concat > elapsed
                                or not 0 < elapsed <= int(samples[i][1])):
                            raise ValueError(f"invalid replay spans in {name}: {row}")
                if args.reply_trace and counters:
                    stamps = re.findall(r"storetrace (\d+) (\d+) (\d+)", log)
                    if len(stamps) != 2 * len(samples):
                        raise ValueError(f"incomplete reply trace in {name}.log")
                    for i, (seq, sent, received) in enumerate(stamps):
                        gap = int(received) - int(sent)
                        if int(seq) != i or not 0 <= gap <= int(samples[i // 2][i % 2]):
                            raise ValueError(f"invalid trace sample {i} in {name}.log")
                park_line = re.search(r"parked calls append/replay (\d+) (\d+)", log)
                if not park_line:
                    raise ValueError(f"missing parked-call counters in {name}.log")
                parked = tuple(map(int, park_line.groups()))
                for index, op in enumerate(("append", "replay")):
                    m = re.search(rf"{op} calls/slept/sleeps (\d+) (\d+) (\d+)", log)
                    calls, slept, sleeps = map(int, m.groups())
                    if calls != 128 * counters or not 0 <= slept <= calls or sleeps < slept or (not slept and sleeps):
                        raise ValueError(f"inconsistent {op} counters in {name}.log")
                    if args.files_check and (sleeps or not parked[index]):
                        raise ValueError(f"{op} did not exercise blocking receive without fallback: {name}")
                    if parked[index] > calls:
                        raise ValueError(f"excess parked {op} calls in {name}.log")
                    if args.reply_trace and counters:
                        gaps = sorted((int(rx) - int(tx)) / 10 for _, tx, rx in stamps[index::2])
                        print(name, op, "publish-to-receive p50/p95/p99 us",
                              *(gaps[math.ceil(p * len(gaps)) - 1] for p in (.5, .95, .99)), flush=True)
                    us = sorted(int(row[index]) / 10 for row in samples)
                    quantiles = [us[math.ceil(p * len(us)) - 1] for p in (.5, .95, .99)]
                    print(name, op, f"calls/slept/sleeps={calls}/{slept}/{sleeps}",
                          f"parked={parked[index]}", "p50/p95/p99 us", *quantiles, flush=True)

    if args.replay_profile:
        write_report(out)


if __name__ == "__main__":
    main()
