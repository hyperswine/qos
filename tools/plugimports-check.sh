#!/bin/sh
# plugimports-check.sh -- Portable plugins bind to the app's runtime by name
# (docs/2026-10-01-IMPORT-TABLE.md): one plugin build loads under two
# different shell builds, a plugin needing a name no app exports is
# refused by name, and one whose RELOC was tampered with is refused by its sha.
set -eu
cd "$(dirname "$0")/.."
W=$(mktemp -d /tmp/plugimports.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s -C qos portable QOSP_OUT="$W/qosp" \
  FPRBUILD_EXTRA="--cflag -DQOS_PLUGIN_LIFETIME_TEST --with tests-host/plugin_lifetime.c" >/dev/null
make -s plugin-qa PROG=tests/plugmini.fpr PLUG_OUT="$W/plugmini.qa" >/dev/null
make -s plugin-qa PROG=tests/plugneeds.fpr PLUG_OUT="$W/plugneeds.qa" >/dev/null
# plugtamp.qa: plugmini.qa with one byte of its RELOC section flipped
python3 - "$W/plugmini.qa" "$W/plugtamp.qa" "$W/plugimporttamp.qa" <<'PY'
import sys
b = open(sys.argv[1], 'rb').read()
head, _, _ = b.partition(b"\n\n"); base = len(head) + 2
sec = {l.split()[0]: (base + int(l.split()[1]), int(l.split()[2])) for l in head.decode().split("\n")[1:]}
for name, output in zip(("RELOC", "IMPORT"), sys.argv[2:]):
    off, n = sec[name]
    assert n > 0, name
    t = bytearray(b)
    t[off + n // 2] ^= 0xFF
    open(output, "wb").write(t)
PY
"${SOL:-sol}" tools/mkdisk.sol "$W/disk.img" 8 "$W/plugmini.qa" "$W/plugneeds.qa" "$W/plugtamp.qa" "$W/plugimporttamp.qa" >/dev/null
make -s qos-app PROG=tests/qload.fpr QA_OUT="$W/a.qa" >/dev/null
run_shell() {
  if ! FPR_DISK="$W/disk.img" timeout 60 "$W/qosp" --yes "$1" >"$W/run.log" 2>&1; then
    cat "$W/run.log" >&2
    return 1
  fi
  grep -q 'plugin publication lifecycle passed' "$W/run.log" || { cat "$W/run.log" >&2; return 1; }
  grep -a "$2" "$W/run.log" || { cat "$W/run.log" >&2; return 1; }
}
run_shell "$W/a.qa" "qload: .*40+2=42"
make -s qos-app PROG=tests/plugimports.fpr QA_OUT="$W/b.qa" >/dev/null
run_shell "$W/b.qa" "plugimports: plugmini under a second shell: 40+2=42; plugneeds: the plugin needs .*which this app does not export; plugtamp: .*RELOC sha256 mismatch.* HOLDS"
