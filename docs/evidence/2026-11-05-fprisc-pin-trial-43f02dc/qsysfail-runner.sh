#!/bin/sh
# usage: qsysfail.sh <qos tree> <fprisc root> <tag> [runs] [VAR=val...]  -- build qosp + tests/qsysfail.qa, run at 4 harts
S=${SCRATCH:?set SCRATCH to a scratch directory}
T=$(cd "$1" && pwd); F=$(cd "$2" && pwd); tag=$3; runs=${4:-3}; shift 4 2>/dev/null || shift $#
out=$S/qf-$tag; rm -rf $out; mkdir -p $out
E="env FPRISC_ROOT=$F FPR_HOME=$T FPR_PATH=$F FPR_FOREIGN=$T/core/foreign.fpr FPR_PORT=0 XDG_CACHE_HOME=$out/cache $*"
cd $T
$E make -s -C qos portable QOSP_OUT=$out/qosp 'FPRBUILD_EXTRA=--cflag -DQOS_BLK_TEST' > $out/build.log 2>&1 || { echo "$tag: host build failed"; exit 1; }
$E make -s qos-app PROG=tests/qsysfail.fpr QA_OUT=$out/qsysfail.qa BUILD=$out/app >> $out/build.log 2>&1 || { echo "$tag: app build failed"; exit 1; }
pass=0; for i in $(seq $runs); do
  (cd $out && $E FPR_HARTS=4 FPR_DISK=$out/d$i.disk ./qosp --yes qsysfail.qa > run$i.log 2>&1)
  grep -q "qsysfail: HOLDS\|=> qsysfail: HOLDS" $out/run$i.log && ! grep -q FAILED $out/run$i.log && pass=$((pass+1))
done
echo "$tag: $pass/$runs pass; $(grep -h '12=' $out/run*.log | sort | uniq -c | tr '\n' ' ')"
