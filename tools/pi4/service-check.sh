#!/bin/sh
# Run on the Pi: isolated real service restart/exhaustion/administrative reset.
# service-check.sh /tmp/qosp-service-check-UNIQUE app.qa qosp
set -eu
base=${1:?unique test directory required}
case "$base" in /tmp/qosp-service-check-*) ;; *) exit 2 ;; esac
[ ! -e "$base" ] || { echo 'test directory already exists' >&2; exit 2; }
mkdir -p "$base"
export QOSP_RUN_DIR="$base/run" QOSP_STATE="$base/state"
export QOSP_LOG="$base/application.log" QOSP_TTY=/dev/null
export QOSP_APP=${2:?app required} QOSP_BIN=${3:?host required}
export FPR_DISK="$base/disk" FPR_HARTS=4 FPR_PORT=0
export QOSP_RESTART_MAX=2 QOSP_RESTART_DELAY_SEC=1 QOSP_RESTART_DELAY_MAX_SEC=2
export QOSP_READY_TIMEOUT_SEC=10 QOSP_STOP_TIMEOUT_SEC=7 QOSP_KILL_TIMEOUT_SEC=2
service=/etc/init.d/S99qosp
trap '"$service" stop >"$base/cleanup.log" 2>&1 || :' EXIT
await_state() {
  desired=$1
  left=150
  while [ "$left" -gt 0 ]; do
    if [ -f "$QOSP_RUN_DIR/state" ] && grep -q "$desired" "$QOSP_RUN_DIR/state"; then return 0; fi
    sleep .1; left=$((left - 1))
  done
  cat "$QOSP_RUN_DIR/state" >&2
  return 1
}
"$service" start
read -r original < "$QOSP_RUN_DIR/ready"
"$service" start
[ "$(cat "$QOSP_RUN_DIR/ready")" = "$original" ]
for restart in 1 2 3; do
  read -r child < "$QOSP_RUN_DIR/ready"
  [ "$child" -gt 1 ]
  # The PID must still identify the particular test host, never another service.
  grep -aq "$QOSP_BIN" "/proc/$child/cmdline"
  kill -KILL "$child"
  if [ "$restart" -lt 3 ]; then
    await_state "running pid=.* restarts=$restart"
    [ "$(cat "$QOSP_RUN_DIR/ready")" != "$child" ]
    echo "supervision: recovered crash $restart"
  else
    await_state 'failed restart-budget-exhausted restarts=2'
    [ ! -e "$QOSP_RUN_DIR/ready" ]
  fi
done
sleep .5
grep -q '^failed restart-budget-exhausted restarts=2$' "$QOSP_RUN_DIR/state"
"$service" restart
await_state 'running pid=.* restarts=0'
grep -q 'portableshutdown: replayed=committed' "$QOSP_LOG"
"$service" stop
grep -q '^stopped$' "$QOSP_RUN_DIR/state"
[ ! -e "$QOSP_RUN_DIR/ready" ]
grep -q 'qosp: shutdown complete' "$QOSP_LOG"
echo 'supervision: duplicate start, two recoveries, finite budget, administrative reset and graceful stop HOLDS'
