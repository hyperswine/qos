#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec "${SOL:-sol}" build.sol "$@"
