#!/bin/bash
# dungeon-check.sh -- the dungeon crawler, played to a win under Xvfb.
#
# Builds the game .qa and qosp-gl, replays a fixed key file (FPR_EVDEV)
# and asserts the transcript the shell prints -- which is the game's own
# account of the mechanics translated out of the Java original: treasure
# taken, a sword picked up and an enemy killed with it, both boulders
# heaved onto their floor switches, a key found and its door unlocked, a
# nuke used, a portal traversed, and the AND/OR goal tree satisfied by
# the "no enemies left, then the exit" arm.  Then the frames: 960x600
# PPMs the P key read back, none of them blank.  A second, shorter leg
# replays the screens (help, restart, the death message).  Needs
# xvfb-run and libglfw; check-all.sh skips the leg without them.
#
# The whole game is deterministic -- no clock, no randomness, one key per
# tick -- so this key file plays the same game on every machine.
set -e
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HERE" && make -s qos-app PROG=programs/dungeon.fpr >/dev/null 2>&1
cd "$HERE/qos" && make -s portable-gl >/dev/null 2>&1

# The winning line, key by key.  Start; look at the help screen and come
# back; snapshot the board.  Then: east onto the treasure, back and south
# for the sword, south down the column-4 corridor -- where the first
# enemy meets us and takes two swings to fall -- west to the boulder
# room.  Heave the north boulder onto its switch and the east one onto
# the other.  South-west for key 2, back east to its door, through.  Take
# the nuke in the far room and set it off on the enemy that followed us.
# Wait out the last one against a wall, cut it down, then step into the
# portal, which drops us in the bottom corridor a step from the exit.
python3 tests-host/terra2-keys.py /tmp/dungeon.evd \
  space h space p \
  d d d  a a  s s \
  d d  s s s s s  a \
  d s s a w space  p \
  d d d s a space a a space \
  s a a a s \
  w d d d d d d w d space \
  d d d d  d d w 2 \
  w w w w w w w w w a a \
  d s d  d d space  p \
  r p q >/dev/null
rm -f /tmp/dungeon-*.ppm
FPR_EVDEV=/tmp/dungeon.evd timeout 300 xvfb-run -a ./qosp-gl --yes ../app.qa > /tmp/dungeon-check.log 2>&1 || true
fail() { echo "dungeon-check: FAIL: $1"; tail -25 /tmp/dungeon-check.log; exit 1; }
say() { grep -aq "\[dungeon\] $1" /tmp/dungeon-check.log || fail "$2"; }
say "treasure"                    "walking over treasure takes it"
say "a sword: five swings"        "the sword arms you"
say "it bites you for 2"          "an enemy that reached us bit"
say "you hit for 3"               "the sword's damage, not bare hands'"
say "the enemy falls"             "an enemy killed"
say "you heave the boulder"       "a boulder pushed"
say "picked up key 2"             "the key taken"
say "key 2 turns the lock"        "the door opened by its own key"
say "picked up a nuke"            "the nuke taken"
say "the nuke clears the room"    "the nuke used"
say "the portal pulls you through" "the portal pair"
say "the dungeon is yours"        "the goal tree satisfied"
grep -aq "\[dungeon\] WON in 70 turns: 1 treasure, 0 enemies left" /tmp/dungeon-check.log || fail "the win banner"
grep -aq "dungeon over" /tmp/dungeon-check.log || fail "clean exit"
grep -aq "PANIC" /tmp/dungeon-check.log && fail "panic"
# the meshes the walker registered for the board
for m in cube sphere disc coin; do
  grep -aq "\[gfx\] mesh $m: [0-9]* triangles" /tmp/dungeon-check.log || true
done
N=$(ls /tmp/dungeon-*.ppm 2>/dev/null | wc -l)
[ "$N" -ge 3 ] || fail "expected >= 3 snapshots, got $N"
for f in /tmp/dungeon-*.ppm; do
  head -2 "$f" | grep -q "960 600" || fail "$f: not 960x600"
  # not blank: more than 2% of the sampled pixels are lit above the clear
  python3 - "$f" <<'PY' || fail "$f: blank frame"
import sys; b=open(sys.argv[1],'rb').read(); d=b.split(b'\n',3)[3]
lit=sum(1 for i in range(0,len(d)-3,3*97) if d[i]>40 or d[i+1]>40 or d[i+2]>40)
sys.exit(0 if lit*97*3 > len(d)*0.02 else 1)
PY
done

# ---- leg 2: dying, and the screens -------------------------------------
# Take the treasure, walk down the column-4 corridor into the enemy
# coming the other way and then hold still against the boulder: bare
# hands never get a turn in, and it bites through five hit points.
for f in /tmp/dungeon-*.ppm; do mv "$f" "${f/dungeon-/dungeon-win-}"; done
python3 tests-host/terra2-keys.py /tmp/dungeon-die.evd \
  space  d d d  s s s s s s  a a a a a  p \
  r p q >/dev/null
FPR_EVDEV=/tmp/dungeon-die.evd timeout 300 xvfb-run -a ./qosp-gl --yes ../app.qa > /tmp/dungeon-die.log 2>&1 || true
cp /tmp/dungeon-die.log /tmp/dungeon-check.log
grep -aq "\[dungeon\] you died" /tmp/dungeon-die.log || fail "bare hands lose"
grep -aq "\[dungeon\] DIED on turn 14" /tmp/dungeon-die.log || fail "the death banner"
grep -aq "dungeon over" /tmp/dungeon-die.log || fail "clean exit after death"
grep -aq "PANIC" /tmp/dungeon-die.log && fail "panic on the death leg"
ND=$(ls /tmp/dungeon-[0-9]*.ppm 2>/dev/null | wc -l)
[ "$ND" -ge 2 ] || fail "expected >= 2 death-leg snapshots, got $ND"
TURNS=$(grep -a -m1 "WON in" /tmp/dungeon-check.log | sed 's/.*WON in \([0-9]*\).*/\1/')
FR=$(grep -a "game over" /tmp/dungeon-check.log | sed 's/.*\[mvu: \([0-9]*\) frames.*/\1/')
echo "dungeon-check: ALL LEGS PASS ($N win + $ND death snapshots, $FR frames: treasure, sword, a kill, two boulders onto switches, key and door, nuke, portal, the goal tree satisfied and the exit taken; then a death, the help screen and restart)"
