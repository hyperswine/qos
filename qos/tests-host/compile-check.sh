#!/bin/sh
# The worker-backed compile bridge (qos/portable/compile.c, ABI v21) against
# a fake daemon, with the address and undefined-behavior sanitizers.
set -eu
cd "$(dirname "$0")"
TASK_TMP=$(mktemp -d /tmp/qos-compile-check.XXXXXX)
SERVER=
trap '[ -z "$SERVER" ] || kill "$SERVER" 2>/dev/null; rm -rf "$TASK_TMP"' EXIT HUP INT TERM
${CC:-cc} -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer \
  -DQOSP_COMPILE_WAIT_S=2 -I../appside compile_check.c ../portable/compile.c -lpthread -o "$TASK_TMP/check"
FPRD_SOCK="$TASK_TMP/none.sock" "$TASK_TMP/check" none
python3 compile_check.py "$TASK_TMP/fprd.sock" > "$TASK_TMP/server.log" 2>&1 &
SERVER=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do [ -S "$TASK_TMP/fprd.sock" ] && break; sleep 0.2; done
FPRD_SOCK="$TASK_TMP/fprd.sock" "$TASK_TMP/check" big
FPRD_SOCK="$TASK_TMP/fprd.sock" "$TASK_TMP/check" silent
FPRD_SOCK="$TASK_TMP/fprd.sock" "$TASK_TMP/check" abandon
echo "compile-check: PASS (a 1 MiB reply whole, no server, a silent server, an abandoned request)"
