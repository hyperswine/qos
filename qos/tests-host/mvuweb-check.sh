#!/bin/sh

# mvuweb-check.sh -- LV.server (programs/mods/liveview.fpr) end to end:
# build tests/mvuweb.fpr, host it under qosp with the MULTI-CONNECTION
# socket tier (net v6) on a scratch port, and drive the LiveView wire
# with curl as TWO clients (cookie jars = lvsid sessions):
#
#   GET  /  x2 concurrently   both served; distinct Set-Cookie lvsid
#   A bump                    a delta against A's baseline
#   B poll                    A's bump arrives as B'S delta (shared
#                             model, per-client baselines)
#   A poll                    count already seen by A: tick-only delta
#   theme (A)                 a reshape {"s":[..]} for A
#   B poll                    the reshape reaches B as ITS full render
#   quit                      answered; the run returns its result
#
# Assumes fpr and qosp are already built (the check-all sweep's state).

set -e
cd "$(dirname "$0")"

PORT=${MVUWEB_PORT:-8123}
OUT=/tmp/mvuweb-check.out
JA=/tmp/mvuweb-ja.txt
JB=/tmp/mvuweb-jb.txt
CURL="curl -s --noproxy 127.0.0.1 --max-time 10"

(cd ../.. && make -s qos-app PROG=tests/mvuweb.fpr >/dev/null 2>&1)

rm -f "$OUT" "$JA" "$JB"
(cd .. && FPR_PORT=$PORT ./qosp --yes ../app.qa > "$OUT" 2>&1) &
QOSP=$!
trap 'kill $QOSP 2>/dev/null || true' EXIT
sleep 2

fail() { echo "mvuweb-check: FAIL: $1"; exit 1; }

$CURL -c "$JA" "http://127.0.0.1:$PORT/" > /tmp/mvuweb-pa.html &
P1=$!
$CURL -c "$JB" "http://127.0.0.1:$PORT/" > /tmp/mvuweb-pb.html &
P2=$!
wait $P1 $P2
PAGE=$(cat /tmp/mvuweb-pa.html)
echo "$PAGE" | grep -q 'id="lv-root"'        || fail "page: no lv-root"
echo "$PAGE" | grep -q 'window.__LV__'       || fail "page: no __LV__ seed"
echo "$PAGE" | grep -q 'data-slot'           || fail "page: livejs client missing"
echo "$PAGE" | grep -q 'setInterval'         || fail "page: STick poll script missing"
echo "$PAGE" | grep -q 'box-sizing'          || fail "page: generated CSS missing"
grep -q lvsid "$JA" || fail "client A: no session cookie"
grep -q lvsid "$JB" || fail "client B: no session cookie"
SA=$(grep lvsid "$JA" | awk '{print $NF}')
SB=$(grep lvsid "$JB" | awk '{print $NF}')
[ "$SA" != "$SB" ] || fail "sessions: both clients got lvsid=$SA"
echo "  page x2 concurrent: CSS + seed + livejs + poll script; sessions $SA/$SB"

D1=$($CURL -b "$JA" -X POST -d '{"msg":"bump","arg":"5"}' "http://127.0.0.1:$PORT/live/event")
echo "$D1" | grep -q '^{"d":{' || fail "A bump: not a delta: got $D1"
echo "$D1" | grep -q '"0":"5"' || fail "A bump delta: got $D1"
D2=$($CURL -b "$JB" -X POST -d '{"msg":"__poll","arg":""}' "http://127.0.0.1:$PORT/live/event")
echo "$D2" | grep -q '^{"d":{' || fail "B poll: not a delta: got $D2"
echo "$D2" | grep -q '"0":"5"' || fail "B poll: A's bump missing: got $D2"
echo "  shared model: A's bump arrived as B's delta"

sleep 1
D3=$($CURL -b "$JA" -X POST -d '{"msg":"__poll","arg":""}' "http://127.0.0.1:$PORT/live/event")
echo "$D3" | grep -q '"0":' && fail "A poll: count re-sent though A saw it: $D3"
echo "$D3" | grep -q '"1":' || fail "A poll: no server-side tick progress: got $D3"
echo "  per-client baselines: A's poll ships only the tick slot"

D4=$($CURL -b "$JA" -X POST -d '{"msg":"theme","arg":""}' "http://127.0.0.1:$PORT/live/event")
echo "$D4" | grep -q '^{"s":\[' || fail "theme: expected a reshape: got $D4"
echo "$D4" | grep -q 'warm'     || fail "theme: reshaped statics lack the flipped class"
D5=$($CURL -b "$JB" -X POST -d '{"msg":"__poll","arg":""}' "http://127.0.0.1:$PORT/live/event")
echo "$D5" | grep -q '^{"s":\[' || fail "B after reshape: expected full render: got $D5"
echo "  reshape: full split to A, and to B on its next poll"

$CURL -b "$JA" -X POST -d '{"msg":"quit","arg":""}' "http://127.0.0.1:$PORT/live/event" >/dev/null
sleep 1
grep -q "lv: server closed" "$OUT" || fail "quit: no result line ($(tail -1 "$OUT"))"
echo "  quit: MQuit answered the request and returned the result"

echo "mvuweb-check: ALL LEGS PASS"
