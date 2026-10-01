#!/bin/sh
# plugimports-check.sh -- Portable plugins bind to the app's runtime by name
# (docs/2026-10-01-IMPORT-TABLE.md): one plugin build loads under two
# different shell builds, and a plugin needing a name no app exports is
# refused by name.
set -eu
cd "$(dirname "$0")/.."
W=$(mktemp -d /tmp/plugimports.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s plugin-qa PROG=tests/plugmini.fpr PLUG_OUT="$W/plugmini.qa" >/dev/null
make -s plugin-qa PROG=tests/plugneeds.fpr PLUG_OUT="$W/plugneeds.qa" >/dev/null
python3 tools/mkdisk.py "$W/disk.img" 8 "$W/plugmini.qa" "$W/plugneeds.qa" >/dev/null
make -s qos-app PROG=tests/qload.fpr QA_OUT="$W/a.qa" >/dev/null
FPR_DISK="$W/disk.img" timeout 60 qos/qosp --yes "$W/a.qa" 2>&1 | tr -d '\r' | grep -a "qload: .*40+2=42"
make -s qos-app PROG=tests/plugimports.fpr QA_OUT="$W/b.qa" >/dev/null
FPR_DISK="$W/disk.img" timeout 60 qos/qosp --yes "$W/b.qa" 2>&1 | tr -d '\r' | grep -a "plugimports: plugmini under a second shell: 40+2=42; plugneeds: the plugin needs .*which this app does not export HOLDS"
