#!/bin/sh
set -eu
tools=$(dirname "$0")
exec "${SOL:-sol}" "$tools/build-sdk-lld.sol" "$tools/sdk/ld-elf.cpp" "$@"
