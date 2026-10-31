#!/bin/sh
# sdk-smoke.sh -- the external-app loop against an INSTALLED toolchain,
# run the way an app author would: outside any checkout, with no GHC or
# cabal on PATH.  What README's "app loop today" section promises.
#
#   ./qos.py toolchain install --prefix /tmp/qos-sdk
#   (move the qos and fprisc checkouts out of sight)
#   sh tools/sdk-smoke.sh /tmp/qos-sdk /tmp/qos-smoke
#
# Checks: `qos new` (min + mvu templates) from an empty directory,
# `qos run` prints each template's expected line, `qos pack --bundle`
# writes dist/<name>/{<name>.qa,qosp,run.sh}, and run.sh works after the
# bundle is copied somewhere else.  Exits nonzero on the first miss.
set -eu

PREFIX=$(cd "$1" && pwd)
WORK=$2
QOS="$PREFIX/bin/qos"

fail() { echo "sdk-smoke: FAIL: $*" >&2; exit 1; }
ok() { echo "sdk-smoke: ok: $*"; }

# a clean PATH: the install's bin, the C toolchain, python3 -- no GHC
# (SDK_SMOKE_EXTRA_PATH: e.g. Homebrew lld on macOS)
PATH="$PREFIX/bin${SDK_SMOKE_EXTRA_PATH:+:$SDK_SMOKE_EXTRA_PATH}:/usr/local/bin:/usr/bin:/bin"
export PATH
unset FPRISC_ROOT FPR_HOME FPR_PATH FPR_FOREIGN QOS_OUT 2>/dev/null || true
for t in ghc cabal; do
  if command -v "$t" >/dev/null 2>&1; then
    echo "sdk-smoke: note: $t is on PATH at $(command -v $t) (not used by the installed toolchain)"
  fi
done
[ -x "$QOS" ] || fail "no $QOS"
[ ! -e "$PREFIX/bin/fpr" ] || fail "$PREFIX/bin/fpr exported (fpr/sol belong to the standalone FP-RISC toolchain)"
[ ! -e "$PREFIX/bin/sol" ] || fail "$PREFIX/bin/sol exported"
[ -x "$PREFIX/libexec/qos-fpr/toolchain/fpr" ] || fail "no private compiler at libexec/qos-fpr/toolchain/fpr"

rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK"

expect() {  # expect FILE STRING
  grep -qF "$2" "$1" || { cat "$1"; fail "expected '$2' in $1"; }
  ok "found '$2'"
}

# 1. min template: new + run
"$QOS" new smokemin --template min
[ -f smokemin/app.fpr ] || fail "qos new did not write smokemin/app.fpr"
"$QOS" run smokemin/app.fpr 2>&1 | tee run-min.out
expect run-min.out "smokemin: ok fold=55"

# 2. explicit standalone mvu template: new + run + pack --bundle
"$QOS" new smokemvu --template mvu
"$QOS" run smokemvu/app.fpr 2>&1 | tee run-mvu.out
expect run-mvu.out "smokemvu: done count=12 note=hi"
"$QOS" pack smokemvu/app.fpr --bundle 2>&1 | tee pack.out
for f in smokemvu.qa qosp run.sh; do
  [ -f "dist/smokemvu/$f" ] || fail "bundle is missing dist/smokemvu/$f"
done
ok "bundle dist/smokemvu/ has smokemvu.qa qosp run.sh"

# 3. the bundle runs on its own, from another directory
mkdir -p elsewhere
cp -R dist/smokemvu elsewhere/
(cd / && "$WORK/elsewhere/smokemvu/run.sh") > bundle.out 2>&1 || { cat bundle.out; fail "run.sh exited nonzero"; }
expect bundle.out "smokemvu: done count=12 note=hi"

echo "sdk-smoke: PASS"
