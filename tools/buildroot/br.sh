#!/bin/sh
set -eu
case "${1:-}" in qemu|rpi4|star64) ;; *) echo 'usage: br.sh qemu|rpi4|star64 [make arguments]' >&2; exit 2;; esac
here=$(CDPATH= cd "$(dirname "$0")" && pwd)
exec "${SOL:-sol}" "$here/br.sol" "$here" "$@"
