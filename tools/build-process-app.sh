#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec "${SOL:-sol}" tools/build-process-app.sol "$@"
