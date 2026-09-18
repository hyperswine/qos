#!/bin/sh

# pos1-check.sh -- POS v1 (programs/pos1.fpr) under qosp's socket
# tier, driven by pos1-check.py as websocket registers: the design's
# example and its adversarial legs (docs/POS1-DESIGN.md S9 and S10).

set -e
cd "$(dirname "$0")"
PORT=${POS1_PORT:-8161}
python3 -c "import websockets" 2>/dev/null || { echo "pos1-check: SKIP (pip install websockets)"; exit 0; }
(cd ../.. && make -s qos-app PROG=programs/pos1.fpr >/dev/null 2>&1) || { echo "pos1-check: FAIL: build"; exit 1; }
(cd .. && make -s portable >/dev/null 2>&1) || { echo "pos1-check: FAIL: qosp build"; exit 1; }
python3 pos1-check.py "$(cd .. && pwd)" ../app.qa "$PORT"
