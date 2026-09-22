#!/bin/bash
# terra2-check.sh -- Terra II, played by a key script under Xvfb.
#
# Builds the game .qa and qosp-gl, replays a fixed key file (FPR_EVDEV),
# and asserts the transcript the rules print (the calls, the attack lunge
# on the HQ, a unit destroyed, the AI's turn), the frames the S key read
# back mid-animation (960x600 PPMs that are not blank), and the sound the
# synthesizer dumped (FPR_SND_DUMP: a WAV as long as the run, with
# distinct bursts over silence).  Needs xvfb-run and libglfw;
# check-all.sh skips the leg without them.
set -e
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HERE" && make -s qos-app PROG=programs/terra2.fpr >/dev/null 2>&1
cd "$HERE/qos" && make -s portable-gl >/dev/null 2>&1
# the cursor stays where the last action left it (the placed unit, the
# attacker), so each turn starts from the board, not the hand
python3 tests-host/terra2-keys.py /tmp/terra2.evd \
  p enter s right right enter enter space \
  enter a up up p enter p space \
  enter a enter down down left enter right enter p space \
  enter a up up enter p space q >/dev/null
rm -f /tmp/terra2-*.ppm /tmp/terra2.wav /tmp/terra2.disk
# music muted here: the effects' bursts over silence are what the WAV
# assertions read; the decoder is proven separately below
# a fresh disk: the profile log is what the second run reads back
FPR_DISK=/tmp/terra2.disk FPR_SND_MUSIC=0 FPR_ASSETS=../models/music FPR_SND_DUMP=/tmp/terra2.wav FPR_EVDEV=/tmp/terra2.evd \
  timeout 300 xvfb-run -a ./qosp-gl --yes ../app.qa > /tmp/terra2-check.log 2>&1 || true
fail() { echo "terra2-check: FAIL: $1"; tail -20 /tmp/terra2-check.log; exit 1; }
grep -aq "profile: 0 games (0 won, 0 lost, 0 abandoned)" /tmp/terra2-check.log || fail "the empty profile"
grep -aq "game saved: turn 5" /tmp/terra2-check.log || fail "the board saved at the turn's start"
grep -aq "you: LightInf called to forward 3" /tmp/terra2-check.log || fail "the call"
grep -aq "you: LightInf attacks the HQ" /tmp/terra2-check.log || fail "the lane attack"
grep -aq "HQ hit for 2: 13 left" /tmp/terra2-check.log || fail "HQ damage"
grep -aq "turn 1 side 1" /tmp/terra2-check.log || fail "the enemy turn"
grep -aq "enemy: .* called to" /tmp/terra2-check.log || fail "the AI's call"
grep -aq "destroyed" /tmp/terra2-check.log || fail "a death"
grep -aq "you: MechInf called to forward 4" /tmp/terra2-check.log || fail "the tank's call"
grep -aq "you: MechInf attacks the HQ" /tmp/terra2-check.log || fail "the tank's shot"
grep -aq "HQ hit for 3: 10 left" /tmp/terra2-check.log || fail "the shell's damage"
grep -aq "music Skyward_Little_World.mp3: muted by FPR_SND_MUSIC=0" /tmp/terra2-check.log || fail "the music call"
grep -aq "\[gfx\] mesh tank_hull: 172 triangles" /tmp/terra2-check.log || fail "the hull mesh"
grep -aq "\[gfx\] mesh tank_turret: 124 triangles" /tmp/terra2-check.log || fail "the turret mesh"
for m in infantry infantry_kit infantry_rifle truck truck_kit truck_canvas hq hq_fence hq_dish; do
  grep -aq "\[gfx\] mesh $m: [0-9]* triangles" /tmp/terra2-check.log || fail "the $m mesh"
done
grep -aq "game over" /tmp/terra2-check.log || fail "clean exit"
grep -aq "PANIC" /tmp/terra2-check.log && fail "panic"
N=$(ls /tmp/terra2-*.ppm 2>/dev/null | wc -l)
[ "$N" -ge 3 ] || fail "expected >= 3 snapshots, got $N"
for f in /tmp/terra2-*.ppm; do
  head -2 "$f" | grep -q "960 600" || fail "$f: not 960x600"
  # not blank: more than 2% of the bytes differ from the clear colour
  python3 - "$f" <<'PY' || fail "$f: blank frame"
import sys; b=open(sys.argv[1],'rb').read(); d=b.split(b'\n',3)[3]
lit=sum(1 for i in range(0,len(d),3*97) if d[i]>40 or d[i+1]>40 or d[i+2]>40)
sys.exit(0 if lit*97*3 > len(d)*0.02 else 1)
PY
done
# the lifecycle, on the same disk: the first run's start record reads
# back as one abandoned game and its board as a game to continue; the
# Keys, Stats and Cards screens from the title, Continue, pause with esc,
# Restart through its confirm, Stats from the menu, quit
for f in /tmp/terra2-*.ppm; do mv "$f" "${f/terra2-/terra2-game-}"; done
python3 tests-host/terra2-keys.py /tmp/terra2-life.evd \
  k p esc s p esc c p right right down p esc t "type:get me.hq" enter "type:set env 4" enter "type:board" enter f1 esc \
  enter esc p down enter p enter esc down down down enter p esc q >/dev/null
FPR_DISK=/tmp/terra2.disk FPR_SND_MUSIC=0 FPR_ASSETS=../models/music FPR_EVDEV=/tmp/terra2-life.evd \
  timeout 120 xvfb-run -a ./qosp-gl --yes ../app.qa > /tmp/terra2-life.log 2>&1 || true
grep -aq "profile: 1 games (0 won, 0 lost, 1 abandoned)" /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "the profile read back"; }
grep -aq "a game is waiting: turn 5" /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "the saved game read back"; }
grep -aq "welcome back: turn 5" /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "continue"; }
grep -aq "term: me.hq = 1[0-9]" /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "the terminal reads the model"; }
grep -aq "term: env = 4" /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "the terminal sets the model"; }
grep -aq "term: me.fwd: " /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "the terminal's board"; }
grep -aq "\[terra2\] paused" /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "pause"; }
grep -aq "\[terra2\] restart: a new game" /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "restart"; }
grep -aq "game over" /tmp/terra2-life.log || { cp /tmp/terra2-life.log /tmp/terra2-check.log; fail "clean exit after the menu"; }
NL=$(ls /tmp/terra2-[0-9]*.ppm 2>/dev/null | wc -l)
[ "$NL" -ge 7 ] || fail "expected >= 7 lifecycle snapshots, got $NL"
# the sound: the mix is as long as the run and carries distinct bursts
# (cursor ticks, the opening riff, calls, blows, turn chimes, the close)
[ -s /tmp/terra2.wav ] || fail "no sound dump"
python3 - /tmp/terra2.wav <<'PY' || fail "sound dump"
import sys, struct
b = open(sys.argv[1], 'rb').read()
assert b[:4] == b'RIFF' and b[8:12] == b'WAVE', "not a WAV"
rate = struct.unpack_from('<I', b, 24)[0]; data = b[44:]
n = len(data) // 2
secs = n / rate
frames = struct.unpack('<%dh' % n, data[:n * 2])
win = rate // 50  # 20 ms windows
loud = [max(abs(x) for x in frames[i:i + win]) > 1500 for i in range(0, n - win, win)]
bursts = sum(1 for i in range(1, len(loud)) if loud[i] and not loud[i - 1])
quiet = 1 - sum(loud) / max(1, len(loud))
print(f"terra2 sound: {secs:.1f} s, {bursts} bursts, {quiet * 100:.0f}% silence")
assert secs > 12, "too short"
assert bursts >= 20, "too few bursts"
assert quiet > 0.3, "never quiet"
PY
# the music channel: three seconds of the track through the decoder,
# read back as a WAV that is not quiet
cd "$HERE" && make -s qos-app PROG=tests/music.fpr >/dev/null 2>&1
cd "$HERE/qos" && rm -f /tmp/music.wav
FPR_SND_DUMP=/tmp/music.wav FPR_ASSETS=../models/music timeout 30 ./qosp --yes ../app.qa > /tmp/music-check.log 2>&1 || true
grep -aq "44100 Hz stereo, looping" /tmp/music-check.log || fail "the MP3 decode"
python3 - /tmp/music.wav <<'PY' || fail "the music mix"
import sys, struct, math
b = open(sys.argv[1], 'rb').read(); data = b[44:]; n = len(data) // 2
fr = struct.unpack('<%dh' % n, data[:n * 2])
rms = math.sqrt(sum(x * x for x in fr[::7]) / max(1, len(fr[::7])))
print(f"music: {n / 44100:.1f} s, rms {rms:.0f}")
assert n > 44100 * 2 and rms > 300
PY
# the game's own .qa is what the leg leaves behind
cd "$HERE" && make -s qos-app PROG=programs/terra2.fpr >/dev/null 2>&1
cd "$HERE/qos"
SND=$(grep -a -m1 "dump closed" /tmp/terra2-check.log | sed 's/.*(\(.*\) s), \(.*\) tones.*/\1 s, \2 tones/')
FR=$(grep -a "game over" /tmp/terra2-check.log | sed 's/.*\[mvu: \([0-9]*\) frames.*/\1/')
echo "terra2-check: ALL LEGS PASS ($N + $NL snapshots, $FR frames, sound $SND: title, call, tracers on the HQ, AI turn, a death, the tank and its shell, the MP3 decoded, clean quit; keys, stats, cards, the terminal, continue, pause, restart, the profile read back)"
