#!/bin/sh
: "${FPRISC_ROOT:?Set FPRISC_ROOT to the fprisc checkout}"

# buddy-check.sh -- buddy.c proven on the host, small blocks so every
# path (split, coalesce, in-place realloc, copy realloc) is cheap to
# reach.  FPR_BUDDY_MIN here must match MIN in buddy_check.c.

set -e
cd "$(dirname "$0")"

gcc -O2 -Wall -Wextra -DFPR_POSIX -DFPR_BUDDY_MIN=4096 \
    -I"$FPRISC_ROOT/runtime" "$FPRISC_ROOT/runtime/buddy.c" buddy_check.c \
    -o /tmp/buddy_check

/tmp/buddy_check
