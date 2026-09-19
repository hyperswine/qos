# qos/Makefile — the QOS backend, built SEPARATELY from the programs.
#
#   make portable          # qosp: the QOS Portable host (unix)
#   make portable-run      # qosp running ../app.qa
#   make native            # qos-native.elf: the kernel (system.fpr) for QEMU virt
#   make native-run        # boot it as a kernel with a seeded disk
#
# QOS Portable is NOT an OS: qosp hosts ONE FP-RISC .qa by satisfying
# its std assumptions through the qos_hal_t table.  QOS Native IS the
# OS: system.fpr compiled AOT for RISC-V, linked with hal/{core,virt},
# loaded by QEMU as the kernel.  Both consume ../hal — the C layer is
# a HAL, not an implementation.  The kernel is itself an FP-RISC
# program, so `native` invokes the fprisc checkout's fpr as a TOOL; the build
# products and dependency graph stay entirely on this side.

include ../dependency.mk

HAL    = ../hal
FPR    = ..

HARTS ?= 2
QOSHARTS ?= 8
# the host arena the app's growth grants come from (mmap'd lazily: only
# touched pages cost RSS).  Sessions, actors, and message slabs all live
# here, so this is the "scale to memory" ceiling for a hosted server.
ARENA_MB ?= 2048
CROSS  = riscv64-unknown-elf-
QEMU   = qemu-system-riscv64
# outputs qos.py redirects into the project's .qos/ (an installed tree is
# never written to); the host binaries qosp / qosp-gl stay beside this file
BUILD  ?= build
KERNEL ?= qos-native.elf
DISK   ?= disk.img
PDISK  ?= qosp.disk
ACCEL  = -accel tcg,thread=multi
TIMEOUT := $(shell command -v timeout 2>/dev/null || echo "")
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
HOST_LDFLAGS :=
DESKTOP_GL_LIBS := $(shell pkg-config --libs glfw3 2>/dev/null) -framework OpenGL -lpthread -lm
# the sound tier (hal/unix/snd_raw.c): AudioQueue on macOS
SND_FLAGS := -DQOSP_SND_AQ
SND_LIBS := -framework AudioToolbox -framework CoreFoundation
else
HOST_LDFLAGS := -no-pie
DESKTOP_GL_LIBS := $(shell pkg-config --libs glfw3 2>/dev/null) -lGL -lpthread -lm
# the sound tier: ALSA when its headers are installed (libasound2-dev),
# else the WAV dump only (FPR_SND_DUMP) -- never a build failure
ALSA_LIBS := $(shell pkg-config --libs alsa 2>/dev/null)
SND_FLAGS := $(if $(ALSA_LIBS),-DQOSP_SND_ALSA,)
SND_LIBS := $(ALSA_LIBS)
endif
DESKTOP_GL_CFLAGS := $(shell pkg-config --cflags glfw3 2>/dev/null)

# ---- QOS Portable: the qosp host ---------------------------------------
QOSP_SRC = portable/host.c portable/sha256.c portable/haltab.c portable/store.c \
           portable/compile.c \
           $(HAL)/unix/net_raw.c $(HAL)/unix/blk_raw.c $(HAL)/unix/hostlog.c \
           $(HAL)/unix/tty_raw.c $(HAL)/unix/evdev_raw.c $(HAL)/unix/mice_raw.c $(HAL)/unix/snd_raw.c \
           ../loader/qaimg.c

# the shell's half of the ABI stamp is DERIVED from the authoritative
# source (Codegen.hs codegenRev), not hardcoded -- the first stamped
# build caught main.c's #define 7 lagging a rev-8 compiler within the
# hour.  Falls back to main.c's #define if the compiler tree is absent.
CODEGEN_REV := $(shell grep -m1 '^codegenRev = ' $(FPRISC_ROOT)/compiler/Codegen.hs 2>/dev/null | grep -o '[0-9]\+' | head -1)
REV_FLAG := $(if $(CODEGEN_REV),-DQOSP_CODEGEN_REV=$(CODEGEN_REV),)

# qosp IS an FP-RISC program (portable/qosp.fpr, a Base program for the posix
# system).  $(QOSP_SRC) is its HAL: the device tiers and the five primitives
# in portable/host.c that qosp.fpr declares and does not define.  `fpr build
# --with` links them beside the runtime; --harts 1 because the host's own
# runtime only ever runs main (the APP's harts are pthreads host.c starts).
# FPR_HOME names the compiler's checkout here: dependency.mk points it at QOS
# for module resolution, and qosp.fpr's `use` lines are importer-relative.
QOSP_FPR = portable/qosp.fpr ../programs/mods/qar.fpr ../programs/mods/manifest.fpr ../programs/mods/qaimg.fpr
QOSP_DEFS = -DQOSP_HOST -DQOS_ARENA_SIZE=($(ARENA_MB)ul<<20) $(REV_FLAG)
# on arm64 the app keeps its hart in x28; the host's C must never borrow it,
# or its fault handler could not ask the app which actor was running
ifneq ($(filter arm64 aarch64,$(shell uname -m)),)
QOSP_DEFS += -ffixed-x28
endif
QOSP_INCS = -I$(HAL)/unix -Iappside -Iportable
fpr_host = FPR_HOME="$(FPRISC_ROOT)" "$(FPRC)" build portable/qosp.fpr -o $(1) --harts 1 \
	  $(foreach f,$(2),--with $(f)) \
	  $(foreach f,$(QOSP_DEFS) $(QOSP_INCS) $(3),--cflag '$(f)') \
	  $(foreach f,$(4),--link $(f))

portable: $(QOSP_SRC) $(QOSP_FPR) appside/qos_abi.h $(FPRISC_ROOT)/compiler/Codegen.hs
	$(call fpr_host,qosp,$(QOSP_SRC),$(SND_FLAGS),$(SND_LIBS))

portable-run: portable
	./qosp --yes $(FPR)/app.qa

# ---- QOS Portable with the desktop-GL gfx tier --------
# GLFW window + OpenGL 3.3-core shaders; keys arrive as SYNTHETIC EVDEV
# (gfx.c translates GLFW keycodes and injects them into evdev_raw's one
# modifier machine, so the appkit keymap and FPR_EVDEV replay are
# untouched).  The same source builds on macOS (OpenGL/gl3.h declares
# prototypes; Linux needs GL_GLEXT_PROTOTYPES, set in gfx.c).
QOSP_GL_SRC = $(QOSP_SRC) $(HAL)/unix/gfx.c
portable-gl: $(QOSP_GL_SRC) $(QOSP_FPR) appside/qos_abi.h $(FPRISC_ROOT)/compiler/Codegen.hs
	$(call fpr_host,qosp-gl,$(QOSP_GL_SRC),-DQOSP_GFX -DFPR_DESKTOP_GL $(SND_FLAGS) $(DESKTOP_GL_CFLAGS),$(DESKTOP_GL_LIBS) $(SND_LIBS))

# ---- QOS Portable, aarch64 cross (verifies the x28 hart discipline
portable-a64: $(QOSP_SRC) appside/qos_abi.h $(FPRISC_ROOT)/compiler/Codegen.hs
	aarch64-linux-gnu-gcc -static -O2 -Wall -Wextra -DFPR_POSIX -DQOSP_HOST -DFPR_NHARTS=$(QOSHARTS) -DQOS_ARENA_SIZE="($(ARENA_MB)ul << 20)" $(REV_FLAG) \
	  -I$(FRUNTIME) -I$(HAL)/unix -Iappside $(QOSP_SRC) -o qosp-a64 -lpthread -lm

# ---- QOS Native: the kernel --------------------------------------------
RT_CORE = $(FRUNTIME)/runtime.c $(FRUNTIME)/actors.c $(FRUNTIME)/bits.c \
          $(FRUNTIME)/vec.c $(FRUNTIME)/sstr.c $(FRUNTIME)/mod.c $(FRUNTIME)/buddy.c
RT_VIRT = $(FMACHINE)/virt/crt0.S $(FMACHINE)/virt/ctx.S $(FMACHINE)/virt/ctx_fab.c \
          $(FMACHINE)/virt/hal.c $(FMACHINE)/virt/memshim.c
ARCHFLAGS = -march=rv64imafdc_zicsr -mabi=lp64 -mcmodel=medany
CFLAGS = $(ARCHFLAGS) -DFPR_NHARTS=$(HARTS) \
         -ffreestanding -nostdlib -nostartfiles -O2 -Wall -Wextra \
         -fno-builtin -fno-stack-protector

# the rodata fallback registry: placeholder .qa's from the manifests
QAPPS = TUIAppLauncher TUINotes TUIClock HelloProc
$(BUILD)/qa0/%.qa: $(FPR)/apps/%.toml $(FPR)/tools/mkqa.py
	@mkdir -p $(BUILD)/qa0
	python3 $(FPR)/tools/mkqa.py $< -o $@

$(BUILD)/apps_data.c: $(patsubst %,$(BUILD)/qa0/%.qa,$(QAPPS)) $(FPR)/tools/genapps.py
	python3 $(FPR)/tools/genapps.py --entries --out $@ -- $(patsubst %,$(BUILD)/qa0/%.qa,$(QAPPS))

$(BUILD)/system.s: $(FPRC) $(FPR)/programs/system.fpr $(FPRISC_ROOT)/core/prelude.fpr FORCE
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --system=qos-native --prelude=$(FPRISC_ROOT)/core/prelude.fpr \
	  $(FPR)/programs/system.fpr $@

# the MACHINE LAYER is the compiler tree's (its CLINT unit is FP-RISC: virt.mk);
# the DEVICES are this tree's (../hal/virt, qos-virt.mk).  One copy of each.
VIRT_MACHINE := $(FMACHINE)
include $(FMACHINE)/virt/virt.mk
QOS_HAL := $(abspath $(HAL))
include $(HAL)/virt/qos-virt.mk

native: $(BUILD)/system.s $(BUILD)/apps_data.c $(RT_VIRT) $(VIRT_FPR) $(QOS_VIRT_HAL) $(RT_CORE) $(FMACHINE)/virt/link.ld
	$(CROSS)gcc $(CFLAGS) -T $(FMACHINE)/virt/link.ld -I$(FRUNTIME) -I$(FMACHINE)/virt \
	  $(RT_VIRT) $(VIRT_FPR) $(QOS_VIRT_HAL) $(BUILD)/system.s $$(cat $(BUILD)/system.s.units) $(RT_CORE) \
	  ../loader/apps.c $(BUILD)/apps_data.c ../loader/qaimg.c ../loader/process.c \
	  -o $(KERNEL)

$(DISK): $(FPR)/tools/mkdisk.py
	python3 $(FPR)/tools/mkdisk.py $(DISK) 8

# ---- the portable disk ---------------------------------------------------
# qosp.disk is a QLOG image -- the SAME format native-run's disk.img
# uses, seeded by the SAME tool.  qosp creates a blank one on first
# `device "blk"` (FPR_DISK / FPR_DISK_MB override path and size);
# `make disk-seed QAS="a.qa b.qa"` installs built .qa apps onto it as
# apps/<Id>.qa records plus the apps/index, ready for the System.qa
# loading path.
disk-seed: $(FPR)/tools/mkdisk.py
	python3 $(FPR)/tools/mkdisk.py $(PDISK) 8 $(QAS)

native-run: native $(DISK)
	$(TIMEOUT) 25 $(QEMU) $(ACCEL) -machine virt -smp $(HARTS) -m 256M \
	  -nographic -bios none -kernel $(KERNEL) \
	  -drive file=$(DISK),if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0

clean:
	rm -rf build qosp qos-native.elf disk.img

FORCE:
.PHONY: portable portable-run native native-run clean FORCE
