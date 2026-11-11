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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
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
    run(["tools/build-process-app.sh", "tests/storewaitbench.fpr", manifest, app])
    for harts in (1, 2):
        kernels = {}
        for counters in (0, 1):
            name = f"{harts}h-stats{counters}"
            kernels[counters] = out / f"{name}.elf"
            run(["make", "-s", "-C", "qos", "native", f"HARTS={harts}",
                 f"SYSTEM={ROOT}/tests/storewaitnative.fpr", f"KERNEL={kernels[counters]}",
                 f"BUILD={out}/{name}", f"NATIVE_CFLAGS_EXTRA=-DQOS_STORE_WAIT_STATS={counters}"])
        for repeat in range(3):
            for counters in ((0, 1) if repeat % 2 == 0 else (1, 0)):
                name = f"{harts}h-stats{counters}-run{repeat + 1}"
                disk = out / f"{name}.img"
                run(["python3", "tools/mkdisk.py", disk, "16", app])
                command = ["qemu-system-riscv64", "-machine", "virt", "-smp", str(harts),
                           "-m", "256M", "-nographic", "-bios", "none", "-kernel", str(kernels[counters]),
                           "-drive", f"file={disk},if=none,format=raw,id=hd0", "-device", "virtio-blk-device,drive=hd0"]
                with (out / f"{name}.log").open("w") as log:
                    subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, timeout=120, check=True)
                log = (out / f"{name}.log").read_text()
                samples = re.findall(r"storewait ticks (\d+) (\d+)", log)
                if len(samples) != 128 or "storewait: DONE" not in log or "PANIC" in log:
                    raise ValueError(f"incomplete workload in {name}.log")
                for index, op in enumerate(("append", "replay")):
                    m = re.search(rf"{op} calls/slept/sleeps (\d+) (\d+) (\d+)", log)
                    calls, slept, sleeps = map(int, m.groups())
                    if calls != 128 * counters or not 0 <= slept <= calls or sleeps < slept or (not slept and sleeps):
                        raise ValueError(f"inconsistent {op} counters in {name}.log")
                    us = sorted(int(row[index]) / 10 for row in samples)
                    quantiles = [us[math.ceil(p * len(us)) - 1] for p in (.5, .95, .99)]
                    print(name, op, f"calls/slept/sleeps={calls}/{slept}/{sleeps}",
                          "p50/p95/p99 us", *quantiles, flush=True)


if __name__ == "__main__":
    main()
