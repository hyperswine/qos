#!/bin/sh
: "${FPRISC_ROOT:?Set FPRISC_ROOT to the fprisc checkout}"

# pkgstore-roundtrip.sh — fpr push/pull against a live pkgstore.
# Needs: the pkgstore server running (uvicorn server:app --port 8323)
# and PKGSTORE_URL if not the default.  Verified flow:
#   commit dep + top (pinned closure) -> push both -> wipe .fpr ->
#   pull both -> consumer compiles entirely from the pulled store.

set -e
FPR=${FPR:-$FPRISC_ROOT/fpr}
T=$(mktemp -d); cd "$T"
echo 'helper x = x + 7.' > dep.fpr
echo 'D = use "dep". probe y = D.helper y.' > probe.fpr
H=$(LC_ALL=C.UTF-8 "$FPR" --target=rv64 probe.fpr /dev/null 2>&1 | grep -o 'dep#[a-f0-9]*' | cut -d'#' -f2 | head -1)
printf 'D = use "dep#%s".\nmainish y = D.helper y.\n' "$H" > top.fpr
"$FPR" commit dep.fpr >/dev/null && "$FPR" commit top.fpr
"$FPR" push dep && "$FPR" push top
TH=$(awk '$1=="top"{print $3}' .fpr/versions.db | tail -1)
rm -rf .fpr
"$FPR" pull dep && "$FPR" pull top
printf 'T = use "top#%s".\nmain = print "{T.mainish 5}".\n' "$TH" > c.fpr
rm dep.fpr top.fpr
LC_ALL=C.UTF-8 "$FPR" --target=rv64 --prelude="$FPRISC_ROOT/core/prelude.fpr" c.fpr /tmp/rt.s
echo "pkgstore round trip OK"
