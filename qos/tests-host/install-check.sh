#!/bin/bash
: "${FPRISC_ROOT:?Set FPRISC_ROOT to the fprisc checkout}"
# install-check.sh -- the tree as a TOOLCHAIN: installed under a prefix,
# then used from an empty directory the way `brew install qos-fpr` would
# be used, with the checkout nowhere in sight.
#
# Asserts: the layout (bin/{fpr,qos,sol} over libexec/qos-fpr, the
# .installed marker); `qos new` + `qos run` of a fresh project whose
# `use "std/..."` resolves under the toolchain's home; `sol` running a
# script that uses the installed lib; `fpr compile` with no --prelude;
# `qos pack --bundle`; and that NOTHING under libexec was written by any
# of it -- the whole point of the workspace.
set -e
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"
P="$T/prefix"
W="$T/work"
fail() { echo "install-check: FAIL: $1"; tail -20 "$T/log" 2>/dev/null; exit 1; }
"$HERE/qos.py" install --prefix "$P" > "$T/log" 2>&1 || fail "install"
for f in bin/fpr bin/qos bin/sol libexec/qos-fpr/.installed libexec/qos-fpr/toolchain/fpr libexec/qos-fpr/qos/qosp \
         libexec/qos-fpr/toolchain/core/prelude.fpr libexec/qos-fpr/toolchain/std/mvu.fpr libexec/qos-fpr/toolchain/runtime/runtime.c; do
  [ -e "$P/$f" ] || fail "missing $P/$f"
done
[ -L "$P/bin/fpr" ] && [ -L "$P/bin/qos" ] || fail "bin/fpr and bin/qos must be symlinks (Home.hs resolves the real path)"
# nothing the tree builds may ship: a .qa, an elf, a build/ dir
BAD=$(cd "$P/libexec/qos-fpr" && find . -name '*.qa' -o -name '*.elf' -o -name 'build' -o -name '*.o' -o -name 'dist-newstyle' | head -3)
[ -z "$BAD" ] || fail "build products in the install: $BAD"
sleep 1; touch "$T/stamp"     # anything under libexec newer than this was written by a run
mkdir -p "$W" && cd "$W"
export PATH="$P/bin:$PATH"
# 1. a project of its own, from nothing
qos new hello --template min > "$T/log" 2>&1 || fail "qos new"
grep -q 'use "std/' hello/app.fpr || fail "a project outside the tree should use \"std/...\" (got: $(grep use hello/app.fpr | head -1))"
qos run hello/app.fpr > "$T/log" 2>&1 || fail "qos run hello"
grep -aq "expect: found" "$T/log" || fail "the template's own expect line"
[ -f .qos/app.qa ] || fail "the .qa should land in the project's .qos/ (got: $(ls -a))"
# 2. an in-tree test program by absolute path (the compiler's home store + std)
qos run "$P/libexec/qos-fpr/toolchain/tests/eq.fpr" > "$T/log" 2>&1 || fail "qos run tests/eq.fpr"
grep -aq "eq: done" "$T/log" || fail "eq.fpr's transcript"
# 3. sol, with the installed lib
printf 'B = use "sol/lib/base".\n> print "sol: {B.max0 7}{B.boolInt True}".\n' > s.sol
sol s.sol > "$T/log" 2>&1 || fail "sol"
grep -aq "sol: 71" "$T/log" || fail "sol's output ($(tail -1 "$T/log"))"
# 4. fpr on its own: no --prelude, the one beside the binary
printf 'main = print "fpr: {List.len (1 :: 2 :: Nil)}".\n' > f.fpr
fpr compile --profile=qos-portable f.fpr f.s > "$T/log" 2>&1 || fail "fpr compile without --prelude"
[ -s f.s ] || fail "fpr compile emitted nothing"
# 5. a bundle someone else can run
qos pack hello/app.fpr --bundle > "$T/log" 2>&1 || fail "qos pack"
[ -x dist/hello/run.sh ] && [ -f dist/hello/hello.qa ] || fail "dist/hello/ layout ($(ls dist/hello 2>/dev/null))"
./dist/hello/run.sh > "$T/log" 2>&1 || fail "the bundle's run.sh"
grep -aq "hello: ok" "$T/log" || fail "the bundle's output"
# 6. the toolchain was never written to
WROTE=$(find "$P/libexec" -newer "$T/stamp" -type f | head -3)
[ -z "$WROTE" ] || fail "a run wrote into the installed tree: $WROTE"
QA=$(ls -la .qos/*.qa | wc -l)
echo "install-check: ALL LEGS PASS (prefix $P: bin/{fpr,qos,sol}; a new project ran, tests/eq.fpr ran by path, sol used the installed lib, fpr compiled with its own prelude, a bundle ran; $QA .qa in the project's .qos/, zero writes under libexec)"
rm -rf "$T"
