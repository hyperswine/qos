#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
fprisc=${FPRISC_ROOT:-../fprisc}
work=$(mktemp -d /tmp/qos-gfx-input-check.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM
if [ "$(uname -s)" = Darwin ]; then
  cc -O2 -DFPR_POSIX -DFPR_DESKTOP_GL -DGL_SILENCE_DEPRECATION -I"$fprisc/runtime" -Ihal/unix -I/opt/homebrew/include \
    qos/tests-host/gfx_input_check.c hal/unix/evdev_raw.c hal/unix/mice_raw.c -L/opt/homebrew/lib -lglfw \
    -framework OpenGL -Wl,-dead_strip -Wl,-undefined,dynamic_lookup -o "$work/check"
else
  cc -O2 -ffunction-sections -fdata-sections -DFPR_POSIX -DFPR_DESKTOP_GL -DGL_SILENCE_DEPRECATION -I"$fprisc/runtime" -Ihal/unix \
    qos/tests-host/gfx_input_check.c hal/unix/evdev_raw.c hal/unix/mice_raw.c $(pkg-config --cflags --libs glfw3 gl) \
    -Wl,--gc-sections -lm -o "$work/check"
fi
"$work/check"
