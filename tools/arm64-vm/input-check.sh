#!/bin/sh
# input-check.sh -- does QOS Portable capture a terminal, a real /dev/input
# keyboard and a mouse on arm64 Linux?  Needs the guest up, provisioned and
# synced (vm.sh), with fpr and qosp built in it.  The keys are pressed from
# OUTSIDE the guest, through QEMU's USB keyboard and mouse.  docs/INPUT.md.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
vm() { "$HERE/vm.sh" ssh "$@"; }
fail=0
leg() { # name, expected (space-joined events), got
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1"; echo "  want: $2"; echo "  got:  $3"; fail=1; fi
}
events() { grep '^event ' | sed 's/^event //' | tr ' ' , | tr '\n' ' ' | sed 's/ $//'; }

"$HERE/vm.sh" sync
vm 'cd qos && make -s qos-app PROG=tests/inputcap.fpr QA_OUT=/tmp/inputcap.qa >/tmp/inputcap.build 2>&1 && mkdir -p /tmp/qvm' || { vm 'tail -5 /tmp/inputcap.build'; exit 1; }
vm 'cat > /tmp/qvm/ptydrive.py' < "$HERE/ptydrive.py"

# 1. the terminal: every key a terminal can say, as evdev codes with the modifier bias
got=$(vm 'python3 /tmp/qvm/ptydrive.py /tmp/inputcap.qa keys' | events)
leg "terminal keys, size, resize" \
  "5,100,30 4,35,1 4,1035,1 5,120,40 4,103,1 4,105,1 4,28,1 4,1,1 4,14,1 4,15,1 4,4030,1 4,8045,1 4,4106,1 4,111,1 4,59,1 4,63,1 4,1015,1 4,1053,1 4,44,1" "$got"

# 2. FPR_EVDEV=<node>: one explicit keyboard, nothing else (press AND release)
kbd=$(vm 'for d in /sys/class/input/event*; do grep -qi "usb keyboard" $d/device/name && basename $d; done | head -1')
vm "cd qos && FPR_EVDEV=/dev/input/$kbd ./qos/qosp --yes /tmp/inputcap.qa 2>&1 </dev/null" > /tmp/qos-inputcheck.$$ &
sleep 3; "$HERE/inject.py" key h shift-h; "$HERE/inject.py" rel 30 -10; wait
leg "FPR_EVDEV=/dev/input/$kbd" "4,35,1 4,35,0 4,1035,1 4,1035,0" "$(events < /tmp/qos-inputcheck.$$)"

# 3. FPR_EVDEV=auto on a terminal: discovered keyboards + the mouse + the size;
#    what is typed into the terminal meanwhile is discarded
vm 'FPR_EVDEV=auto python3 /tmp/qvm/ptydrive.py /tmp/inputcap.qa quiet' > /tmp/qos-inputcheck.$$ &
sleep 4; "$HERE/inject.py" key h shift-h; sleep 0.3; "$HERE/inject.py" rel 30 -10; sleep 0.3; "$HERE/inject.py" btn left; wait
leg "FPR_EVDEV=auto: keyboard + mouse" "5,100,30 5,120,40 4,35,1 4,35,0 4,1035,1 4,1035,0 2,30,10 3,1,0 3,0,0" "$(events < /tmp/qos-inputcheck.$$)"
grep '^\[input\]' /tmp/qos-inputcheck.$$ | sed 's/^/     /'
rm -f /tmp/qos-inputcheck.$$
[ $fail = 0 ] && echo "input-check: all ok" || { echo "input-check: FAILED"; exit 1; }
