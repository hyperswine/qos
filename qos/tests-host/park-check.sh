#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
build=$(mktemp -d /tmp/qos-park-check.XXXXXX)
trap 'rm -rf "$build"' EXIT HUP INT TERM
${CC:-cc} -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pthread \
  qos/portable/park.c qos/tests-host/park_check.c -o "$build/check"
"$build/check"
