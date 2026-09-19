#!/bin/sh
# qainfo-parity.sh -- the capability blob, end to end.  For each manifest: pack
# it with tests/capsecho.fpr's image, launch it under qosp --yes, and compare
# the blob the app RECEIVED through its boot record with the blob
# mods/manifest.fpr computes (tools/qainfo.fpr).  Byte for byte.
#
# It began as the check that held qosp's C manifest parser to the FP-RISC
# one.  qosp is an FP-RISC program now and uses the same module, so what
# this guards is the path: manifest -> gate -> blob -> boot record -> Sys.caps.
#
# The manifests are the shipped ones plus a generated one past every limit
# the C parser used to have: 300 permissions (was 32), a 1000-byte url
# (was 95), a blob well over 4 KiB.
#
# Assumes fpr and qosp are built (./qos.py build).
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
FPRISC=$(./qos.py fprisc 2>/dev/null | sed -n 's/.*fprisc: \(\/[^ ]*\) .*/\1/p' | head -1)
[ -n "$FPRISC" ] || { echo "qainfo-parity: cannot find the fprisc checkout"; exit 2; }
WORK=$(mktemp -d "${TMPDIR:-/tmp}/qainfo-parity.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

"$FPRISC/fpr" build tools/qainfo.fpr -o "$WORK/qainfo" >/dev/null
./qos.py run tests/capsecho.fpr >/dev/null 2>&1 </dev/null
ELF=$(ls .qos/build/qosapp-a64.elf .qos/build/qosapp.elf 2>/dev/null | head -1)
ABI=$("$WORK/qainfo" .qos/capsecho.qa | sed -n 's/^abi = //p')

mkdir "$WORK/gen"
python3 - "$WORK/gen/big.toml" <<'PY'
import sys
m = 'name = "Big"\nid = "big"\nentry = "n/a"\nversion = "1"\nloadMode = "process"\n\n[permissions.required]\n'
m += "".join(f'"/services/p{i}" = "read"\n' for i in range(300))
m += '\n[permissions.optional]\n"/services/' + "x" * 1000 + '" = "write"\n'
open(sys.argv[1], "w").write(m)
PY

fails=0
for toml in apps/*.toml "$WORK/gen/big.toml"; do
  name=$(basename "$toml" .toml)
  # stamp the abi the host gates on, and launch as a process image
  { grep -v '^abi\|^loadMode' "$toml" | awk -v abi="$ABI" 'NR==1{print "abi = \"" abi "\"\nloadMode = \"process\""} {print}'; } > "$WORK/$name.toml"
  python3 tools/mkqa.py "$WORK/$name.toml" "$ELF" -o "$WORK/$name.qa" >/dev/null
  (cd "$WORK" && "$ROOT/qos/qosp" --yes "$name.qa" 2>/dev/null </dev/null) \
    | sed -n '/^CAPS-BEGIN$/,/^CAPS-END$/p' | sed '1d;$d' > "$WORK/$name.host"
  "$WORK/qainfo" "$WORK/$name.qa" --caps > "$WORK/$name.fpr"
  if cmp -s "$WORK/$name.host" "$WORK/$name.fpr" && [ -s "$WORK/$name.fpr" ]; then
    echo "  ok   $name: $(($(wc -l < "$WORK/$name.fpr") - 2)) grants, $(wc -c < "$WORK/$name.fpr" | tr -d ' ') bytes"
  else
    echo "  FAIL $name"; diff "$WORK/$name.host" "$WORK/$name.fpr" | head -5; fails=$((fails + 1))
  fi
done
[ "$fails" -eq 0 ] && echo "qainfo-parity: ALL AGREE" || { echo "qainfo-parity: $fails disagree"; exit 1; }
