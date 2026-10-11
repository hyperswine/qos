#!/bin/sh
set -eu
cd "$(dirname "$0")"
TASK_TMP=$(mktemp -d /tmp/qos-blkflush-check.XXXXXX)
trap 'rm -rf "$TASK_TMP"' EXIT HUP INT TERM
cat > "$TASK_TMP/hostlog.c" <<'EOF'
#include <stdarg.h>
#include <stdio.h>
void qos_hostlog(const char *fmt, ...) {
  va_list ap; va_start(ap, fmt); vfprintf(stderr, fmt, ap); fputc('\n', stderr); va_end(ap);
}
EOF
SANITIZERS=
[ "${QOS_BLK_ASAN:-0}" != 1 ] || SANITIZERS="-fsanitize=address,undefined -fno-omit-frame-pointer"
${CC:-cc} -O1 -g -Wall -Wextra -Werror $SANITIZERS -DQOS_BLK_TEST \
  -I../../hal/unix blkflush_check.c "$TASK_TMP/hostlog.c" -lpthread -o "$TASK_TMP/check"
"$TASK_TMP/check"
