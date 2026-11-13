"""Compatibility interface for the Sol QAR2 packer."""
import argparse
import os
from pathlib import Path
import subprocess


def build(manifest_path, elf_path, out_path, relocatable=False,
          check_moved_elf=None, check_delta=0, with_imports=False, native_abi=None,
          plane_abis=None):
    tools = Path(__file__).resolve().parent
    sol = os.environ.get("SOL", "sol")
    if not elf_path or elf_path == "-" or not Path(elf_path).exists():
        if relocatable:
            raise SystemExit("mkqa: a relocatable archive requires an ELF image")
        args = [tools / "qa-placeholder.sol", manifest_path, out_path]
    elif not relocatable:
        args = [tools / "qa-pack.sol", "fixed", manifest_path, elf_path, out_path]
    else:
        mode = "plugin" if with_imports else "process"
        versions = []
        if native_abi is not None:
            mode = "native-plugin" if with_imports else "native"
            versions = [str(native_abi), *map(str, plane_abis or ())]
        args = [tools / "qa-pack.sol", mode, manifest_path, elf_path, check_moved_elf or "",
                str(check_delta), out_path, *versions]
    result = subprocess.run([sol, *args])
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("elf", nargs="?", default="-")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--relocatable", action="store_true",
                    help="the ELF is linked at 0 with --emit-relocs: write a RELOC section (native process images)")
    ap.add_argument("--check-moved", metavar="ELF",
                    help="the same image linked --delta higher: verify the RELOC list against it")
    ap.add_argument("--delta", type=lambda x: int(x, 0), default=0)
    ap.add_argument("--imports", action="store_true",
                    help="write an IMPORT section from the image's __qosimp_ markers (Portable plugins)")
    ap.add_argument("--native-abi", type=int, help="shared runtime ABI for a native process image")
    ap.add_argument("--plane-abis", type=int, nargs=2, metavar=("ACTORS", "MEMORY"),
                    help="the plane actors and memory contract versions the process was compiled against")
    a = ap.parse_args()
    if a.native_abi is not None and (not a.relocatable or not 1 <= a.native_abi <= 999999999):
        ap.error("--native-abi needs --relocatable and a positive version of at most nine digits")
    if a.imports and not a.relocatable:
        ap.error("--imports needs --relocatable")
    if a.plane_abis is not None and (a.native_abi is None or not all(1 <= v <= 999999999 for v in a.plane_abis)):
        ap.error("--plane-abis needs --native-abi and two positive versions of at most nine digits")
    build(a.manifest, a.elf, a.out, a.relocatable, a.check_moved, a.delta, a.imports, a.native_abi,
          tuple(a.plane_abis) if a.plane_abis is not None else None)
