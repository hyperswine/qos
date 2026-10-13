#!/bin/bash
set -euo pipefail
# Run inside ARM64 Linux with the Buildroot SDK and sibling FP-RISC checkout.
[ "$(uname -s)-$(uname -m)" = Linux-aarch64 ] || {
  echo 'Build this bundle on ARM64 Linux (tools/arm64-vm).' >&2; exit 2;
}
qos=$(cd "$(dirname "$0")/../.." && pwd)
fprisc=${FPRISC_ROOT:-$(dirname "$qos")/fprisc}
out=${1:-$qos/.qos/pi4/validation/bundle}
cc=${TARGET_CC:-$HOME/.cache/qosp-br/rpi4/host/bin/aarch64-buildroot-linux-gnu-gcc}
mkdir -p "$out"
out=$(cd "$out" && pwd)
"$cc" -O2 -Wall -Wextra "$qos/tools/pi4/runner.c" -o "$out/runner"
make -s -C "$qos/qos" portable-es QOSP_ES_OUT="$out/qosp-es" \
  FPRBUILD_EXTRA="--cc $cc --cflag -g --cflag -DQOS_BLK_TEST --cflag -DQOS_STORE_TEST" \
  SND_FLAGS=-DQOSP_SND_ALSA SND_LIBS=-lasound
echo 'built diagnostic EGL host'
cd "$fprisc"
for name in strprims bitrange longpanic killblocked deadmail autodrop2 fixedheap sleepwake sleepwait taskstress mvufailure mvuscoped deadlines taskfailure mvudeadlines arenamigrate vecwide veccaps typedvector vecsimd_int bigheap overflow files; do
  extra=()
  if [ "$name" = taskfailure ]; then extra=(--with tests/base/actorfail_probe.c); fi
  ./fpr build "tests/base/$name.fpr" -o "$out/$name" --harts 4 --cc "$cc" "${extra[@]}"
  echo "built base/$name"
done
for name in fvec2 fmath actors; do
  ./fpr build "tests/$name.fpr" -o "$out/$name" --harts 4 --cc "$cc"
  echo "built $name"
done
for name in fib sha pingpong xpingpong nbody vecread; do
  ./fpr build "tests/bench/$name.fpr" -o "$out/bench-$name" --harts 4 --cc "$cc"
  cp "tests/bench/$name.expected" "$out/bench-$name.expected"
  echo "built bench/$name"
done
cp tests/base/strprims.expected "$out/strprims.expected"
cd "$qos"
for name in blockportable blocknamespace blocklifecyclep blockmemory filessvc filesshutdown qlogmemory gfxshare gfxmemory gfxsmoke gfxheadless guishell panemvu appsession appjobs portableshutdown qsys netactor netactorstart nettransport; do
  make -s qos-app-a64 PROG="tests/$name.fpr" QA_OUT="$out/$name.qa" BUILD="$out/build-$name"
  echo "built qos/$name"
done
for name in plugmini plughello; do
  make -s plugin-qa-a64 PROG="tests/$name.fpr" PLUG_OUT="$out/$name.qa" BUILD="$out/build-$name"
done
python3 tools/mkdisk.py "$out/qsys.disk" 8 "$out/plugmini.qa" "$out/plughello.qa"
echo 'BUNDLE COMPLETE'
python3 - "$qos" "$fprisc" "$out" "$cc" <<'PYMETA'
import hashlib, json, pathlib, subprocess, sys
qos, fprisc, out, cc = sys.argv[1:]
def tree(path):
    head = subprocess.check_output(['git', '-C', path, 'rev-parse', 'HEAD'], text=True).strip()
    diff = subprocess.check_output(['git', '-C', path, 'diff', 'HEAD'])
    return {'head': head, 'tracked_diff_sha256': hashlib.sha256(diff).hexdigest()}
files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
         for p in pathlib.Path(out).iterdir() if p.is_file() and p.name != 'manifest.json'}
manifest = {'qos': tree(qos), 'fprisc': tree(fprisc), 'cc': cc, 'files': files,
            'cc_version': subprocess.check_output([cc, '--version'], text=True).splitlines()[0],
            'harts': 4, 'fault_injection': ['QOS_BLK_TEST', 'QOS_STORE_TEST']}
pathlib.Path(out, 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
PYMETA
