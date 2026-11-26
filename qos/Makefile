# qos/Makefile — compatibility wrapper for QOS backends and QEMU/disk targets.
# Host and kernel build logic lives in tools/build-host.sol and tools/build-native.sol.
include ../dependency.mk

HAL    = ../hal
SOL    ?= sol
FPR    = ..

HARTS ?= 2
QOSHARTS ?= 8
QEMU   = qemu-system-riscv64
BUILD  ?= build
KERNEL ?= qos-native.elf
DISK   ?= disk.img
PDISK  ?= qosp.disk
ACCEL  = -accel tcg,thread=multi
TIMEOUT := $(shell command -v timeout 2>/dev/null || echo "")

QOSP_SRC = portable/host.c portable/sha256.c portable/haltab.c portable/store.c \
           portable/compile.c portable/park.c \
           $(HAL)/unix/net_raw.c $(HAL)/unix/blk_raw.c $(HAL)/unix/hostlog.c \
           $(HAL)/unix/tty_raw.c $(HAL)/unix/evdev_raw.c $(HAL)/unix/mice_raw.c $(HAL)/unix/snd_raw.c \
           ../loader/qaimg.c
QOSP_FPR = portable/qosp.fpr ../programs/mods/qar.fpr ../programs/mods/manifest.fpr ../programs/mods/qaimg.fpr
QOSP_GL_SRC = $(QOSP_SRC) $(HAL)/unix/gfx.c
RT_CORE = $(FRUNTIME)/runtime.c $(FRUNTIME)/actors.c $(FRUNTIME)/bits.c \
          $(FRUNTIME)/vec.c $(FRUNTIME)/sstr.c $(FRUNTIME)/mod.c $(FRUNTIME)/buddy.c

CODEGEN_REV := $(shell grep -m1 '^codegenRev = ' $(FPRISC_ROOT)/compiler/Codegen.hs 2>/dev/null | grep -o '[0-9]\+' | head -1)
REV_FLAG := $(if $(CODEGEN_REV),-DQOSP_CODEGEN_REV=$(CODEGEN_REV),)
QOSP_ARCH ?= $(shell uname -m)

QOSP_OUT ?= qosp
portable: $(QOSP_OUT)
$(QOSP_OUT): $(QOSP_SRC) $(QOSP_FPR) $(RT_CORE) $(FPRC) $(FPRISC_ROOT)/core/prelude.fpr appside/qos_abi.h portable/park.h $(FPRISC_ROOT)/compiler/Codegen.hs
	QOSP_ARCH="$(QOSP_ARCH)" QOSP_OUT="$(QOSP_OUT)" FPRBUILD_EXTRA="$(FPRBUILD_EXTRA)" "$(FPRC)" sol ../tools/build-host.sol plain "$(QOSP_OUT)"

portable-run: portable
	./qosp --yes $(FPR)/app.qa

portable-gl: qosp-gl
qosp-gl: $(QOSP_GL_SRC) $(QOSP_FPR) $(RT_CORE) $(FPRC) $(FPRISC_ROOT)/core/prelude.fpr appside/qos_abi.h portable/park.h $(FPRISC_ROOT)/compiler/Codegen.hs
	QOSP_ARCH="$(QOSP_ARCH)" FPRBUILD_EXTRA="$(FPRBUILD_EXTRA)" "$(FPRC)" sol ../tools/build-host.sol gl qosp-gl

ES_GL_LIBS ?= -lEGL -lGLESv2 -lpthread -lm
QOSP_ES_OUT ?= qosp-es
portable-es: $(QOSP_GL_SRC) $(QOSP_FPR) appside/qos_abi.h portable/park.h $(FPRISC_ROOT)/compiler/Codegen.hs
	QOSP_ARCH="$(QOSP_ARCH)" ES_GL_LIBS="$(ES_GL_LIBS)" FPRBUILD_EXTRA="$(FPRBUILD_EXTRA)" "$(FPRC)" sol ../tools/build-host.sol es "$(QOSP_ES_OUT)"

portable-a64: $(QOSP_SRC) appside/qos_abi.h portable/park.h $(FPRISC_ROOT)/compiler/Codegen.hs
	aarch64-linux-gnu-gcc -static -O2 -Wall -Wextra -DFPR_POSIX -DQOSP_HOST -DFPR_NHARTS=$(QOSHARTS) $(REV_FLAG) \
	  -I$(FRUNTIME) -I$(HAL)/unix -Iappside $(QOSP_SRC) -o qosp-a64 -lpthread -lm

XLEN ?= 64
ifeq ($(XLEN),32)
QEMU = qemu-system-riscv32
endif
ACTORS_SRC ?= $(FRUNTIME)/actors.c
SYSTEM ?= $(FPR)/programs/system.fpr
NATIVE_CFLAGS_EXTRA ?=
native: portable/sha256.c $(SYSTEM) $(FPRC)
	XLEN=$(XLEN) HARTS=$(HARTS) BUILD="$(abspath $(BUILD))" SYSTEM="$(abspath $(SYSTEM))" KERNEL="$(abspath $(KERNEL))" ACTORS_SRC="$(ACTORS_SRC)" NATIVE_CFLAGS_EXTRA="$(NATIVE_CFLAGS_EXTRA)" NATIVE_TEST_SRC="$(NATIVE_TEST_SRC)" "$(FPRC)" sol ../tools/build-native.sol "$(abspath $(KERNEL))"

$(DISK): $(FPR)/tools/mkdisk.sol $(FPR)/tools/qlog-seed.sol $(FPR)/tools/qlog-preserve.sol
	"$(SOL)" $(FPR)/tools/mkdisk.sol $(DISK) 8

disk-seed: $(FPR)/tools/mkdisk.sol $(FPR)/tools/qlog-seed.sol $(FPR)/tools/qlog-preserve.sol
	"$(SOL)" $(FPR)/tools/mkdisk.sol $(PDISK) 8 $(QAS)

native-run: native $(DISK)
	$(TIMEOUT) 25 $(QEMU) $(ACCEL) -machine virt -smp $(HARTS) -m 256M \
	  -nographic -bios none -kernel $(KERNEL) \
	  -drive file=$(DISK),if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0

clean:
	rm -rf build qosp qosp-gl qosp-es qos-native.elf disk.img

FORCE:
.PHONY: portable portable-run portable-gl portable-es portable-a64 native native-run clean FORCE
