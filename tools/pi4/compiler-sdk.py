#!/usr/bin/env python3
"""Compatibility entry point for builds using the previous installer path."""
import os
from pathlib import Path
import sys

script = Path(__file__).resolve().with_suffix(".sol")
sol = os.environ.get("SOL", "sol")
args = sys.argv[1:]
# Historical callers could launch the packager from outside the checkout.
if not any(arg == "--qos" or arg.startswith("--qos=") for arg in args):
    args = ["--qos", str(script.parents[2]), *args]
# --sol used to select the bootstrap runtime as well as the bundled runtime.
for index, arg in enumerate(args):
    if arg == "--sol" and index + 1 < len(args):
        sol = args[index + 1]
    elif arg.startswith("--sol="):
        sol = arg.partition("=")[2]
if not os.environ.get("SOL") and sol == "sol":
    import shutil
    if not shutil.which(sol):
        for index, arg in enumerate(args):
            if arg.startswith("--compiler=") or (arg == "--compiler" and index + 1 < len(args)):
                compiler = arg.partition("=")[2] if "=" in arg else args[index + 1]
                os.execv(Path(compiler).absolute(), [compiler, "sol", str(script), *args])
os.execvp(sol, [sol, str(script), *args])
