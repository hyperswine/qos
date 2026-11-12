# checks/prelude.sh -- what every leg's shell starts from.  Sourced by the
# script checks/sweep.sol writes for a leg, which has set:
#   SWEEP_TREE      the tree this leg builds and runs in
#   SWEEP_WORK      scratch that belongs to this leg's worker
#   SWEEP_OUT       the sweep's output directory (shared caches, service verdicts)
#   SWEEP_COMPILER  the FP-RISC checkout under test
#   SWEEP_MARK      where a skip is recorded
#
# A leg sees only the environment set here.  Compiler, device and
# fault-injection variables from the caller's shell (and the toolchain
# launcher that started the runner) must not reach a run.
set -uo pipefail
for name in $(compgen -e); do
  case "$name" in
    FPR_*|FPRD_*|QOSP_*|QOS_BLK_*|QOS_STORE_TEST*|CK_*|MAKEFLAGS|MFLAGS|MAKEOVERRIDES|BUILD|PROG|QA_OUT|HARTS|QOSHARTS)
      unset "$name" ;;
  esac
done
export FPRISC_ROOT="$SWEEP_COMPILER"
export FPR_HOME="$SWEEP_TREE"
export FPR_PATH="$SWEEP_COMPILER"
export FPR_FOREIGN="$SWEEP_TREE/core/foreign.fpr"
export FPR_DISK="$SWEEP_WORK/default.disk"
export XDG_CACHE_HOME="$SWEEP_WORK/cache"
export CK_TMP="$SWEEP_WORK/ck"
export TMPDIR="$SWEEP_WORK/tmp" TMP="$SWEEP_WORK/tmp" TEMP="$SWEEP_WORK/tmp"
# one object cache for every tree: objects are named by their content
export QOS_OBJ_CACHE="$SWEEP_OUT/objects"
mkdir -p "$CK_TMP" "$TMPDIR" "$XDG_CACHE_HOME" "$QOS_OBJ_CACHE"
cd "$SWEEP_TREE" || exit 1
ROOT="$(pwd)"

# ran CMD...: a pipeline stage whose exit status is not the verdict -- a
# refusal the leg expects (the compiler naming an error, qosp refusing a
# tampered archive, a Sol transaction failing on purpose) or a boot that
# `timeout` ends.  pipefail would fail the leg on it; the grep after it is
# the check.  Use it only there: a stage whose status IS the verdict stays bare.
ran() { "$@" || true; }
# A skipped leg is not a pass: the runner counts it apart.
leg_skipped() { echo "skipped ($1)"; printf '%s\n' "$1" > "$SWEEP_MARK.skipped"; }
# The service checks run once beside the legs (tools/check-services.py);
# a service leg reads its verdict.
service_leg() { python3 tools/check-services.py --verdict "$1" --results "$SWEEP_OUT/services/results.json"; }
