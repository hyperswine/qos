"""Inventory one qualified Spectre app before assigning hardware cycle costs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("build", type=Path)
parser.add_argument("app", choices=["hello", "spin", "pendulum", "ping", "pong"])
args = parser.parse_args()
root = args.build
app = root / "boot/apps" / args.app


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


manifest = {}
for row in (root / "SHA256SUMS").read_text().splitlines():
    expected, name = row.split(maxsplit=1)
    if digest(root / name) != expected:
        raise SystemExit(f"build artifact hash mismatch: {name}")
    manifest[name] = expected

# Objdump reads the ELF; confirm its flat executable is the payload on the card.
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    binary = Path(tmp) / "app.bin"
    subprocess.run(["riscv64-unknown-elf-objcopy", "-O", "binary",
                    app.with_suffix(".elf"), binary], check=True)
    package = bytes.fromhex(app.with_suffix(".sxa").read_text())
    if binary.read_bytes() != package[12:]:
        raise SystemExit("ELF and packaged payload differ")

symbol = "fpr_fn_main"
disassembly = subprocess.check_output(
    ["riscv64-unknown-elf-objdump", "-d", "--disassemble=" + symbol,
     app.with_suffix(".elf")], text=True)
insns = re.findall(r"^\s*[0-9a-f]+:\s+[0-9a-f]+\s+[^\n]+", disassembly, re.M)
report = re.search(r"^# native-insns-v1: main (.+)$",
                   app.with_suffix(".s").read_text(), re.M)
if not insns or not report:
    raise SystemExit("missing linked main or compiler report")
inputs = (root / "build-inputs.txt").read_text().splitlines()
print(json.dumps({
    "fprisc": {"checkout": inputs[3], "compiler_sha256": inputs[4].split()[0],
               "runtime": inputs[0].split()[1]},
    "qos_native": {"checkout_at_build": inputs[2], "kernel_sha256": manifest["boot/fs.bin"]},
    "spectre": {"board_sources": inputs[1].split()[1],
                "fpga_sha256": manifest["boot/patched-pre.fs"]},
    "app": args.app, "sxa_sha256": digest(app.with_suffix(".sxa")),
    "symbol": symbol, "compiler_native_insns_v1": report[1],
    "linked_main_static_instruction_sites": len(insns),
    "wcet_cycles": None,
}, indent=2))
