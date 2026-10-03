#!/bin/sh
# plugimports-check.sh -- Portable plugins bind to the app's runtime by name
# (docs/2026-10-01-IMPORT-TABLE.md): one plugin build loads under two
# different shell builds, a plugin needing a name no app exports is
# refused by name, and one whose RELOC was tampered with is refused by its sha.
set -eu
cd "$(dirname "$0")/.."
W=$(mktemp -d /tmp/plugimports.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s plugin-qa PROG=tests/plugmini.fpr PLUG_OUT="$W/plugmini.qa" >/dev/null
make -s plugin-qa PROG=tests/plugneeds.fpr PLUG_OUT="$W/plugneeds.qa" >/dev/null
# plugtamp.qa: plugmini.qa with one byte of its RELOC section flipped
python3 - "$W/plugmini.qa" "$W/plugtamp.qa" <<'PY'
import sys
b = open(sys.argv[1], 'rb').read()
head, _, _ = b.partition(b"\n\n"); base = len(head) + 2
sec = {l.split()[0]: (base + int(l.split()[1]), int(l.split()[2])) for l in head.decode().split("\n")[1:]}
off, n = sec["RELOC"]; t = bytearray(b); t[off + n // 2] ^= 0xFF
open(sys.argv[2], 'wb').write(bytes(t))
PY
python3 tools/mkdisk.py "$W/disk.img" 8 "$W/plugmini.qa" "$W/plugneeds.qa" "$W/plugtamp.qa" >/dev/null
make -s qos-app PROG=tests/qload.fpr QA_OUT="$W/a.qa" >/dev/null
FPR_DISK="$W/disk.img" timeout 60 qos/qosp --yes "$W/a.qa" 2>&1 | tr -d '\r' | grep -a "qload: .*40+2=42"
make -s qos-app PROG=tests/plugimports.fpr QA_OUT="$W/b.qa" >/dev/null
FPR_DISK="$W/disk.img" timeout 60 qos/qosp --yes "$W/b.qa" 2>&1 | tr -d '\r' | grep -a "plugimports: plugmini under a second shell: 40+2=42; plugneeds: the plugin needs .*which this app does not export; plugtamp: .*RELOC sha256 mismatch.* HOLDS"
