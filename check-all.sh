#!/bin/sh
# check-all.sh -- the whole sweep, one leg after another, in this tree.
#
# The legs are in checks/legs and the runner is ./sweep (checks/sweep.sol).
# This is the serial form of it, kept under the name qos.py and the notes use;
#   ./sweep --jobs 6 --output build/sweep/<new dir>
# runs the same legs several at a time in private copies of the tree.
exec "$(dirname "$0")/sweep" --in-place "$@"
