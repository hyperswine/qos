#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
W=$(mktemp -d /tmp/qsys-check.XXXXXX)
trap 'rm -rf "$W"' EXIT INT TERM
make -s qos-app PROG=tests/qsys.fpr
make -s plugin-qa PROG=tests/plugmini.fpr
make -s plugin-qa PROG=tests/plughello.fpr
python3 tools/mkdisk.py "$W/disk.img" 8 plugmini.qa plughello.qa >/dev/null
for boot in 1 2; do
  FPR_DISK="$W/disk.img" timeout 60 qos/qosp --yes app.qa >"$W/boot$boot.out" 2>&1
  grep -F "qsys: boot #$boot; 2 apps [plugmini,plughello]; ping=pong from a .qa read off qosp.disk; hello=plughello: the second sub-slot; 21+21=42; note=$((boot * 3))B;" "$W/boot$boot.out"
done
echo 'qsys: two boots HOLDS'
