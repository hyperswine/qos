#!/bin/sh
# Run a bounded command with a temporary CPU policy; restore every policy on
# exit. Put runner OUTSIDE the application but INSIDE this guard, so its
# deadline survives SSH disconnect and the guard restores after runner exits.
set -eu
umask 077
requested=${1:?usage: cpu-policy-run.sh keep|powersave|performance command...}
shift
case "$requested" in keep|powersave|performance) ;; *) exit 2 ;; esac
[ "$#" -gt 0 ] || exit 2
root=${QOSP_CPU_POLICY_ROOT:-/sys/devices/system/cpu/cpufreq}
lock=${QOSP_CPU_POLICY_LOCK:-/tmp/qosp-cpu-policy.lock}
mkdir "$lock" || { echo 'CPU policy is owned by another run' >&2; exit 1; }
restore() {
  status=$?
  trap - EXIT
  for saved in "$lock"/policy*; do
    [ -f "$saved" ] || continue
    target="$root/$(basename "$saved")/scaling_governor"
    original=$(cat "$saved")
    if ! printf '%s\n' "$original" > "$target"; then status=1; fi
    actual=$(cat "$target")
    echo "[cpu-policy] restored $(basename "$saved")=$actual" >&2
    [ "$actual" = "$original" ] || status=1
    rm "$saved"
  done
  rmdir "$lock" || status=1
  exit "$status"
}
trap restore EXIT
# The bounded runner keeps ownership after a disconnected SSH client.
trap '' HUP
cancelled=0
trap 'cancelled=130' INT
trap 'cancelled=143' TERM
found=0
for policy in "$root"/policy[0-9]*; do
  [ -d "$policy" ] || continue
  found=1
  original=$(cat "$policy/scaling_governor")
  printf '%s\n' "$original" > "$lock/$(basename "$policy")"
  echo "[cpu-policy] before $(basename "$policy")=$original min=$(cat "$policy/scaling_min_freq") max=$(cat "$policy/scaling_max_freq")" >&2
  if [ "$requested" != keep ]; then
    case " $(cat "$policy/scaling_available_governors") " in
      *" $requested "*) ;; *) echo 'Requested governor unavailable' >&2; exit 1 ;;
    esac
    printf '%s\n' "$requested" > "$policy/scaling_governor"
    [ "$(cat "$policy/scaling_governor")" = "$requested" ] || exit 1
  fi
done
[ "$found" = 1 ] || { echo 'No CPU policies found' >&2; exit 1; }
"$@" &
child=$!
status=0
# An interrupted wait must not restore policy while its bounded command is
# still running. Let the runner finish its owned child and reap it first.
while :; do
  if wait "$child"; then status=0; else status=$?; fi
  kill -0 "$child" 2>/dev/null || break
done
[ "$cancelled" = 0 ] || status=$cancelled
exit "$status"
