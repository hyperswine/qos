#!/bin/sh
# Older Buildroot output trees retain this hook path in .config.
: "${BR2_EXTERNAL_QOSP_PATH:=$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)}"
export BR2_EXTERNAL_QOSP_PATH
exec "${SOL:-sol}" "$(dirname "$0")/post-build.sol" "$@"
