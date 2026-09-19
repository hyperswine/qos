#!/bin/sh

# fprlive-check.sh -- POS v2 on FPRLive (tests/pos.fpr) under
# qosp's socket tier, driven by fprlive-check.py as well-behaved and
# adversarial websocket clients.  Assumes fpr and qosp are built (the
# check-all sweep's state) and python3 with `websockets`.

set -e
cd "$(dirname "$0")"
PORT=${FPRLIVE_PORT:-8151}
python3 -c "import websockets" 2>/dev/null || { echo "fprlive-check: SKIP (pip install websockets)"; exit 0; }
(cd ../.. && make -s qos-app PROG=tests/pos.fpr >/dev/null 2>&1) || { echo "fprlive-check: FAIL: build"; exit 1; }
python3 fprlive-check.py "$(cd .. && pwd)" ../app.qa "$PORT"
