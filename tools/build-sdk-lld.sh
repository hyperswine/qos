#!/bin/sh
# build-sdk-lld.sh -- the static ld.lld the QOS Portable SDK ships (toolchain/ld.lld).
#
#   tools/build-sdk-lld.sh WORKDIR        -> WORKDIR/ld.lld
#
# Apple's tools cannot link ELF and the Command Line Tools have no lld, so the
# SDK carries its own (docs/2026-11-01-SDK-PROCESS-APPS.md, step 4).  This is
# lld's ELF driver alone, at the LLVM release Homebrew's llvm is, linked
# against Homebrew's STATIC LLVM libraries for the three QOS targets (AArch64,
# RISC-V, x86-64; lld's LTO needs their code generators).  The result links
# only system libraries: libSystem, libc++ and libz.
#
# Needs: Homebrew llvm and zstd (static libs), cmake, ninja, git, network
# (a sparse clone of llvm/llvm-project: lld/, cmake/, libunwind/include).
set -eu
WORK=$(mkdir -p "$1" && cd "$1" && pwd)
LLVM=$(brew --prefix llvm)
ZSTD=$(brew --prefix zstd)
VERSION=$("$LLVM/bin/llvm-config" --version)
TARGETS="AArch64;RISCV;X86"

if [ ! -d "$WORK/llvm-project" ]; then
  git clone --depth 1 --filter=blob:none --sparse --branch "llvmorg-$VERSION" \
    https://github.com/llvm/llvm-project.git "$WORK/llvm-project"
  git -C "$WORK/llvm-project" sparse-checkout set lld cmake libunwind/include
fi

# A copy of Homebrew's LLVM CMake package that links the static libraries
# (Homebrew's forces libLLVM.dylib), names only three targets, and takes zstd
# statically.
CFG="$WORK/llvm-cmake"
rm -rf "$CFG" && mkdir -p "$CFG" && cp -R "$LLVM/lib/cmake/llvm/." "$CFG/"
sed -i '' 's/^set(LLVM_LINK_LLVM_DYLIB ON)/set(LLVM_LINK_LLVM_DYLIB OFF)/' "$CFG/LLVMConfig.cmake"
sed -i '' "s/^set(LLVM_TARGETS_TO_BUILD .*/set(LLVM_TARGETS_TO_BUILD $TARGETS)/" "$CFG/LLVMConfig.cmake"
sed -i '' "s#^get_filename_component(LLVM_INSTALL_PREFIX \"\${CMAKE_CURRENT_LIST_FILE}\" REALPATH)#set(LLVM_INSTALL_PREFIX \"$LLVM\")#" "$CFG/LLVMConfig.cmake"
sed -i '' '/^get_filename_component(LLVM_INSTALL_PREFIX "${LLVM_INSTALL_PREFIX}" PATH)/d' "$CFG/LLVMConfig.cmake"
sed -i '' "s#^set(LLVM_CMAKE_DIR .*#set(LLVM_CMAKE_DIR \"$CFG\")#" "$CFG/LLVMConfig.cmake"
sed -i '' "s#^get_filename_component(_IMPORT_PREFIX \"\${CMAKE_CURRENT_LIST_FILE}\" PATH)#set(_IMPORT_PREFIX \"$LLVM\")#" "$CFG/LLVMExports.cmake"
sed -i '' '/^get_filename_component(_IMPORT_PREFIX "${_IMPORT_PREFIX}" PATH)/d' "$CFG/LLVMExports.cmake"
sed -i '' 's#/opt/homebrew/lib/libz3.dylib;##g; s#zstd::libzstd_shared#zstd::libzstd_static#g' "$CFG/LLVMExports.cmake"

BUILD="$WORK/build"
mkdir -p "$BUILD/include/llvm/Config"
# The target lists InitializeAllTargets() expands, cut to the three.
for f in Targets AsmPrinters AsmParsers Disassemblers TargetMCAs TargetExegesis; do
  awk '/^LLVM_[A-Z_]*\(/{ if ($0 ~ /\((AArch64|RISCV|X86)\)/) print; next } {print}' \
    "$LLVM/include/llvm/Config/$f.def" > "$BUILD/include/llvm/Config/$f.def"
done
cmake -S "$WORK/llvm-project/lld" -B "$BUILD" -G Ninja -DLLVM_DIR="$CFG" -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_INCLUDE_TESTS=OFF -DCMAKE_C_COMPILER=/usr/bin/clang -DCMAKE_CXX_COMPILER=/usr/bin/clang++ \
  -DCMAKE_OSX_DEPLOYMENT_TARGET="$(sw_vers -productVersion | cut -d. -f1).0" \
  -DLLVM_USE_STATIC_ZSTD=ON -Dzstd_LIBRARY="$ZSTD/lib/libzstd.a" -Dzstd_STATIC_LIBRARY="$ZSTD/lib/libzstd.a" >/dev/null
ninja -C "$BUILD" lldELF lldCommon lld >/dev/null

# lld's own driver links every flavour; the SDK needs ELF only.
cat > "$BUILD/ld-elf.cpp" <<'CPP'
// ld.lld for the QOS Portable SDK: lld's ELF driver alone.
#include "lld/Common/Driver.h"
#include "llvm/Support/InitLLVM.h"
#include "llvm/Support/raw_ostream.h"
LLD_HAS_DRIVER(elf)
int main(int argc, const char **argv) {
  llvm::InitLLVM x(argc, argv);
  std::vector<const char *> args(argv, argv + argc);
  lld::Result r = lld::lldMain(args, llvm::outs(), llvm::errs(), {{lld::Gnu, &lld::elf::link}});
  return r.retCode;
}
CPP
LIBS=$(ninja -C "$BUILD" -t commands lld | tail -1 | tr ' ' '\n' | grep -E '\.a$|\.tbd$|^-l' \
  | grep -v -E 'lldCOFF|lldMachO|lldMinGW|lldWasm|LibDriver|WindowsDriver|WindowsManifest|libxml2' | sed "s#^lib/#$BUILD/lib/#")
MIN="-mmacosx-version-min=$(sw_vers -productVersion | cut -d. -f1).0"
/usr/bin/clang++ -std=c++17 -O2 -DNDEBUG -fno-rtti $MIN -I"$WORK/llvm-project/lld/include" -I"$BUILD/include" \
  -I"$LLVM/include" -c "$BUILD/ld-elf.cpp" -o "$BUILD/ld-elf.o"
# shellcheck disable=SC2086
/usr/bin/clang++ -O2 $MIN -Wl,-dead_strip -Wl,-dead_strip_dylibs -Wl,-no_warn_duplicate_libraries \
  "$BUILD/ld-elf.o" $LIBS -o "$WORK/ld.lld"
strip -x "$WORK/ld.lld"
if otool -L "$WORK/ld.lld" | tail -n +2 | grep -v -E '^\s*/usr/lib/' ; then
  echo "build-sdk-lld: ld.lld links a library outside the system" >&2; exit 1
fi
"$WORK/ld.lld" --version
echo "$WORK/ld.lld"
