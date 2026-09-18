#!/bin/sh
: "${FPRISC_ROOT:?Set FPRISC_ROOT to the fprisc checkout}"
# verify.sh -- the verification slice for the QOS C backend
# (docs/VERIFICATION.md).  Three tools, three targets, each skipped
# with a message when its tool is absent:
#
#   pbt    Hypothesis drives hal/core/buddy.c through ctypes: random
#          alloc/realloc/free sequences, invariants after every step
#          (seconds; needs python3 + hypothesis)
#   spin   the SPSC channel of actors.c as a Promela model: assertions,
#          the ring bound as LTL, delivery under weak fairness
#          (seconds; needs spin + gcc)
#   cbmc   bounded model checking of one buddy alloc/free cycle with
#          CBMC's bounds and pointer checks (minutes; needs cbmc and
#          VERIFY_CBMC=1 -- opt-in because of the runtime)
set -eu
cd "$(dirname "$0")"
root=../../..
fails=0

if python3 -c 'import hypothesis' 2>/dev/null; then
  gcc -O1 -shared -fPIC -DFPR_POSIX -DFPR_BUDDY_MIN=64 -I${FPRISC_ROOT}/hal/core ${FPRISC_ROOT}/hal/core/buddy.c -o /tmp/libbuddy-verify.so
  BUDDY_SO=/tmp/libbuddy-verify.so python3 pbt_buddy.py || fails=$((fails + 1))
else
  echo "pbt buddy: skipped (pip install hypothesis)"
fi

if command -v spin >/dev/null 2>&1; then
  work=$(mktemp -d /tmp/spsc-verify.XXXXXX)
  cp spsc.pml "$work/" && (cd "$work" && spin -a spsc.pml >/dev/null && gcc -O2 -o pan pan.c 2>/dev/null \
    && ./pan 2>&1 | grep -q 'errors: 0' && ./pan -a -N bounded 2>&1 | grep -q 'errors: 0' \
    && ./pan -a -f -N delivered 2>&1 | grep -q 'errors: 0') \
    && echo "spin spsc: assertions (written slot, FIFO), [] count <= CAP, <> delivered under weak fairness: errors 0" \
    || { echo "spin spsc: FAILED"; fails=$((fails + 1)); }
  rm -rf "$work"
else
  echo "spin spsc: skipped (apt install spin)"
fi

if [ "${VERIFY_CBMC:-0}" = 1 ] && command -v cbmc >/dev/null 2>&1; then
  cbmc buddy_cbmc.c ${FPRISC_ROOT}/hal/core/buddy.c -I${FPRISC_ROOT}/hal/core -DFPR_POSIX -DFPR_BUDDY_MIN=64 \
    --unwind 8 --unwindset buddy_init.0:26 --unwinding-assertions --slice-formula > /tmp/buddy-cbmc.out 2>&1 \
    && grep -q 'VERIFICATION SUCCESSFUL' /tmp/buddy-cbmc.out \
    && echo "cbmc buddy: one alloc/free cycle over a 4-block arena: $(grep -c ': SUCCESS' /tmp/buddy-cbmc.out) properties, VERIFICATION SUCCESSFUL" \
    || { echo "cbmc buddy: FAILED (see /tmp/buddy-cbmc.out)"; fails=$((fails + 1)); }
else
  echo "cbmc buddy: skipped (VERIFY_CBMC=1 and cbmc on PATH to run; ~5 minutes)"
fi

[ "$fails" -eq 0 ] && echo "verify: OK" || { echo "verify: $fails failure(s)"; exit 1; }
