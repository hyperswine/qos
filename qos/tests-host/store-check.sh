#!/bin/sh
set -eu
cd "$(dirname "$0")"
TASK_TMP=$(mktemp -d /tmp/qos-store-check.XXXXXX)
trap 'rm -rf "$TASK_TMP"' EXIT HUP INT TERM
SANITIZERS=
[ "${QOS_STORE_ASAN:-0}" != 1 ] || SANITIZERS="-fsanitize=address,undefined -fno-omit-frame-pointer"
${CC:-cc} -O1 -g -Wall -Wextra -Werror $SANITIZERS -DQOS_STORE_TEST \
  -I../appside store_check.c -lpthread -o "$TASK_TMP/check"
python3 store_check.py "$TASK_TMP/check" "$TASK_TMP/data"
