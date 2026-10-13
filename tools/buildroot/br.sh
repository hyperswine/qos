#!/bin/sh
# br.sh -- build a QOS Portable image with Buildroot.
#
#   br.sh qemu  [make args...]   aarch64 QEMU virt: the test loop
#   br.sh rpi4  [make args...]   Raspberry Pi 4: an SD card image
#   br.sh star64 [make args...]  STAR64 Linux bring-up: an SD card image
#
# With no make args it builds everything.  Anything else is handed to
# Buildroot, so `br.sh qemu menuconfig`, `br.sh qemu qosp-rebuild` and
# `br.sh rpi4 linux-menuconfig` all work.
#
# Needs a LINUX build machine (Buildroot does not run on macOS) and a
# Buildroot checkout: $BUILDROOT, default ~/buildroot (STAR64 uses
# ~/buildroot-2026.08).  tools/arm64-vm
# is the one this repo already keeps for that.  Output trees are per
# target under $QOSP_BR_O, default ~/.cache/qosp-br.
#
# The QOS targets do NOT build the application: an image hosts one .qa, and which
# one is the point of the image.  Build it first --
#
#   make -C <qos> qos-app PROG=programs/terra2.fpr     # writes app.qa
#
# and BR2_PACKAGE_QOSP_APP names it (empty = that app.qa).  See README.md.
# STAR64 currently builds Linux and diagnostics without a QOS application.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)

case "${1:-}" in
qemu) CFG=qosp_qemu_aarch64_defconfig ;;
rpi4) CFG=qosp_rpi4_defconfig ;;
star64)
  CFG=qosp_star64_defconfig
  BUILDROOT=${BUILDROOT:-$HOME/buildroot-2026.08}
  ;;
*) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
TARGET=$1
shift
BUILDROOT=${BUILDROOT:-$HOME/buildroot}

[ -f "$BUILDROOT/Makefile" ] || {
  echo "br.sh: no Buildroot at $BUILDROOT" >&2
  if [ "$TARGET" = star64 ]; then
    echo "br.sh: extract https://buildroot.org/downloads/buildroot-2026.08.tar.xz" >&2
    echo "br.sh: into $BUILDROOT (see board/qosp/star64/README.md)" >&2
  else
    echo "br.sh: git clone --depth 1 -b 2025.02.x \\" >&2
    echo "br.sh:   https://gitlab.com/buildroot.org/buildroot.git $BUILDROOT" >&2
  fi
  exit 1
}

if [ "$TARGET" = star64 ] && ! grep -q '^config BR2_PACKAGE_MESA3D_GALLIUM_DRIVER_SOFTPIPE$' "$BUILDROOT/package/mesa3d/Config.in"; then
  echo "br.sh: star64 needs Buildroot 2026.08 (see board/qosp/star64/README.md)" >&2
  exit 1
fi

O=${QOSP_BR_O:-$HOME/.cache/qosp-br}/$TARGET
mkdir -p "$O"
br() { make -C "$BUILDROOT" O="$O" BR2_EXTERNAL="$HERE" "$@"; }

# the defconfig is applied once; after that the tree's .config is the
# truth, so `menuconfig` survives a rebuild
[ -f "$O/.config" ] || br "$CFG"
br "$@"

echo
echo "br.sh: $TARGET images in $O/images"
ls -la "$O/images" 2>/dev/null || true
