#!/bin/sh
# Pixel-only KMS presentation check: no DRM device or display is opened.
set -eu
cd "$(dirname "$0")/../.."
if [ "$(uname -s)" != Linux ]; then
    echo "DRM scanout pixel check skipped (Linux headers required)"
    exit 0
fi
work=$(mktemp -d /tmp/qos-drm-check.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
"${CC:-cc}" -O2 -Wall -Wextra -Ihal/unix qos/tests-host/drm_scanout_check.c -o "$work/check"
"$work/check"
