#!/bin/sh
set -eu
[ "$(uname -s)-$(uname -m)" = Linux-aarch64 ] || {
  echo 'Build this bundle on ARM64 Linux (tools/arm64-vm).' >&2; exit 2;
}
qos=$(CDPATH= cd "$(dirname "$0")/../.." && pwd)
exec "${SOL:-sol}" "$qos/tools/pi4-build.sol" "$qos" "$@"
