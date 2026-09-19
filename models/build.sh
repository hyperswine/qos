#!/bin/sh
# build.sh -- regenerate every model: .coscad -> .scad (coscad) -> .stl
# (OpenSCAD, headless, 10-sided curves) -> <model>.fpr (tools/mkmesh.py).
# All four stages are checked in; run this only after editing a .coscad.
#   COSCAD=/path/to/coscad models/build.sh
set -e
cd "$(dirname "$0")"
: "${COSCAD:=coscad}"
part() { "$COSCAD" "$1.coscad" >/dev/null && xvfb-run -a openscad -o "$1.stl" -D '$fn=10' "$1.scad" >/dev/null 2>&1; }
for p in tank/tank_hull tank/tank_turret infantry/infantry infantry/infantry_kit infantry/infantry_rifle \
         truck/truck truck/truck_kit truck/truck_canvas hq/hq hq/hq_fence hq/hq_dish; do part "$p"; done
python3 ../tools/mkmesh.py tank/tank.fpr tank_hull=tank/tank_hull.stl tank_turret=tank/tank_turret.stl
python3 ../tools/mkmesh.py infantry/infantry.fpr infantry=infantry/infantry.stl infantry_kit=infantry/infantry_kit.stl infantry_rifle=infantry/infantry_rifle.stl
python3 ../tools/mkmesh.py truck/truck.fpr truck=truck/truck.stl truck_kit=truck/truck_kit.stl truck_canvas=truck/truck_canvas.stl
python3 ../tools/mkmesh.py hq/hq.fpr hq=hq/hq.stl hq_fence=hq/hq_fence.stl hq_dish=hq/hq_dish.stl
