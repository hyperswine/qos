#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
work=$(mktemp -d /tmp/qos-pointer-check.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Ihal/unix qos/tests-host/pointer_check.c -o "$work/check"
"$work/check"
