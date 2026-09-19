#!/bin/bash

# gfx-gl-check.sh -- the FPR_DESKTOP_GL branch,
# exercised under Xvfb.  Builds qosp-gl, runs the smoke .qa (GLFW
# window + GL context + FBO readback to PPM), then drives real X key
# events (h, shift+h) into the window and asserts they arrive as
# synthetic evdev 35 / 1035 -- the shift bias proving the events went
# through evdev_raw's one modifier machine.

set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE" && make -s qos-app PROG=tests/gfxsmoke.fpr >/dev/null 2>&1
cd "$HERE/../qos" && make -s portable-gl >/dev/null
rm -f /tmp/gfx-smoke.ppm
timeout 30 xvfb-run -a ./qosp-gl --yes ../fp-risc/app.qa > /tmp/ck-gl.out 2>&1
grep -q "desktopgl. GLFW" /tmp/ck-gl.out
grep -q "ppm rc=0" /tmp/ck-gl.out
head -2 /tmp/gfx-smoke.ppm | grep -q "640 480"
cd "$HERE" && make -s qos-app PROG=tests/gfxkeys.fpr >/dev/null 2>&1
cd "$HERE/../qos"
cat > /tmp/ck-gl-drive.sh <<'DRV'
#!/bin/bash
./qosp-gl --yes ../fp-risc/app.qa > /tmp/ck-glkeys.out 2>&1 &
QPID=$!
for i in $(seq 1 50); do
  WID=$(xdotool search --name "FPRISC Desktop GL" 2>/dev/null | head -1)
  [ -n "$WID" ] && break
  sleep 0.2
done
if [ -n "$WID" ]; then
  xdotool windowactivate --sync $WID 2>/dev/null || true
  sleep 0.5
  xdotool key h || true
  sleep 0.5
  xdotool key shift+h || true
fi
wait $QPID || true
DRV
chmod +x /tmp/ck-gl-drive.sh
timeout 60 xvfb-run -a /tmp/ck-gl-drive.sh >/dev/null 2>&1 || true
grep -q "gfx keys: 35 1035" /tmp/ck-glkeys.out
echo "desktop GL: window+FBO+PPM green; GLFW h/shift+h -> synthetic evdev 35/1035 (one modifier machine)"
