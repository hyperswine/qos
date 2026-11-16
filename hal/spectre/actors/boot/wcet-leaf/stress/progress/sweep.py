"""Replay normal startup and three stale BTB tag assignments at five stack placements."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess

stacks = ["80380000", "80381a80", "80381b80", "80381bc0", "80380050"]
modes = [(None, 0)] + [(seed, pattern) for seed in (0,256,512) for pattern in range(3)]

def simulate(case):
    stack, (seed, pattern), cold = case
    args = ["obj_dir/Vtb", "+limit=256", "+stack="+stack, "+pattern="+str(pattern)]
    if cold:
        args.append("+cold")
    if seed is not None:
        args.append("+seed="+str(seed))
    path = Path("runs") / f"{stack}-{int(cold)}-{pattern}-{seed}.log"
    with path.open("w") as log:
        subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=True)
    if sum(row.startswith("W ") for row in path.read_text().splitlines()) != 256:
        raise ValueError(f"incomplete {path}")

Path("runs").mkdir(exist_ok=True)
with ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(simulate, [(sp, mode, cold) for sp in stacks for mode in modes for cold in (False, True)]))
