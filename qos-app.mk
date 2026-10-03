# ---- QOSPortable profile: the app side ---------------------------------
# The .qa is freestanding at the published slot; every effect goes
# through the qos_hal_t table (qos/appside/hal.c).  The HOST is built
# separately: make -C qos portable.
# macOS reserves 0x180000000-0x7000000000 in every process (the dyld
# shared region, then a no-access block): an address hint in there is never
# honoured, so Darwin hosts and the apps linked for them sit at 1 TiB.
# qos_abi.h makes the same choice for the host; the macOS app rules pass it
# down because their freestanding ELF target does not define __APPLE__.
ifeq ($(shell uname -s),Darwin)
QOS_SLOT_BASE  = 0x10000000000
else
QOS_SLOT_BASE  = 0x400000000
endif
QOS_BASE_FLAG  = -DQOS_ARENA_BASE=$(QOS_SLOT_BASE)ul
# the app's notion of "the heap" (fpr_in_heap) comes from the boot record at
# run time.  It used to be linked in here as ARENA_MB and had to agree with
# the host's (found as random corruption past ~220 sessions): docs/2026-09-19-BOUNDS.md
QOSHARTS ?= 8
QOSAPP_RT_COMMON = $(QOS)/appside/entry.c $(QOS)/appside/hal.c $(QOS)/appside/support.c \
				   $(FRUNTIME)/runtime.c $(FRUNTIME)/actors.c $(FRUNTIME)/bits.c \
				   $(FRUNTIME)/vec.c $(FRUNTIME)/sstr.c $(FRUNTIME)/mod.c \
				   $(FRUNTIME)/buddy.c loader/qaimg.c $(QOS)/portable/sha256.c
QOSAPP_RT = $(QOSAPP_RT_COMMON) $(FMACHINE)/unix/ctx_x64.S

$(BUILD)/qosapp-prog.s: fprc $(SOURCE) $(FPRISC_ROOT)/core/prelude.fpr FORCE
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --system=qos-portable --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $@

# FORCE: the .s is regenerated every time, and a make with 1-second mtimes
# (Apple's 3.81) otherwise packs the PREVIOUS program's image into this .qa
# Two links: the first learns the image's symbols, tools/mkexports.py writes
# the export table plugins complete their imports from (by NAME), and the
# second links it in (docs/2026-10-01-IMPORT-TABLE.md)
QOSAPP_X64_LINK = gcc -O2 -Wall -Wextra -ffreestanding -nostdlib -nostartfiles -static \
	  -fno-stack-protector -fno-asynchronous-unwind-tables -fno-pic -mcmodel=large \
	  -DFPR_POSIX -DFPR_QOSAPP -DFPR_NHARTS=$(QOSHARTS) -DFPR_SLAB_SZ=$(QOSSLAB) -DFPR_STACK_SZ=$(QOSSTACK) $(QOSCFLAGS_EXTRA) \
	  -I$(FRUNTIME) -I$(QOS)/appside \
	  -T $(QOS)/appside/link-qosapp.ld -Wl,--emit-relocs \
	  -Wl,--defsym=_heap_start=_proc_image_end -Wl,--defsym=_heap_end=_proc_image_end \
	  -Wl,--build-id=none -Wl,-z,noexecstack \
	  $(BUILD)/qosapp-prog.s $$(cat $(BUILD)/qosapp-prog.s.units) $(QOSAPP_RT)

# FORCE: the .s is regenerated every time, and a make with 1-second mtimes
# (Apple's 3.81) otherwise packs the PREVIOUS program's image into this .qa
$(BUILD)/qosapp.elf: $(BUILD)/qosapp-prog.s $(QOSAPP_RT) $(QOS)/appside/link-qosapp.ld tools/mkexports.py FORCE
	$(QOSAPP_X64_LINK) -Wl,--defsym=QOS_SLOT_BASE=0 -Wl,--unresolved-symbols=ignore-all -o $(BUILD)/qosapp.pre.elf
	python3 tools/mkexports.py $(BUILD)/qosapp.pre.elf -o $(BUILD)/qosapp-exports.s
	$(QOSAPP_X64_LINK) -Wl,--defsym=QOS_SLOT_BASE=0 $(BUILD)/qosapp-exports.s -o $@
	$(QOSAPP_X64_LINK) -Wl,--defsym=QOS_SLOT_BASE=0x10000000 $(BUILD)/qosapp-exports.s -o $(BUILD)/qosapp.moved.elf

qos-app-x64: $(BUILD)/qosapp.elf tools/mkqa.py
	@MF=$(BUILD)/qosapp-gen.toml; ID=$$(basename $(SOURCE) .fpr); \
	ABIV=$$(grep -m1 'define QOS_ABI_VERSION' $(QOS)/appside/qos_abi.h | grep -o '[0-9]\+' | head -1); \
	REV=$$(cat $(BUILD)/qosapp-prog.s.abirev 2>/dev/null || echo 0); \
	printf 'name = "%s"\nid = "%s"\nentry = "n/a"\nversion = "1"\nloadMode = "process"\nabi = "%s.%s"\n' $$ID $$ID $$ABIV $$REV > $$MF; \
	python3 tools/mkqa.py $$MF $(BUILD)/qosapp.elf -o $(QA_OUT) \
	  --relocatable --check-moved $(BUILD)/qosapp.moved.elf --delta 0x10000000
	@echo "$(QA_OUT) built (relocatable) — run with: (make -C qos portable && qos/qosp --yes $(QA_OUT))"

# ---- QOS app for an AArch64 host: Apple Silicon, arm64 Linux (a Pi 4) --------
# qosp's in-process loader consumes fixed-slot ELF on every host.  Apple
# Clang + lld can cross-link that AArch64 ELF without a Linux sysroot because
# the app and runtime are freestanding.  The code still executes under Darwin,
# where x18 is platform-reserved, so the generic ELF compiler must not use it.
# Mach-O emission remains available separately for native macOS integration work.
$(BUILD)/qosapp-a64.s: fprc $(SOURCE) $(FPRISC_ROOT)/core/prelude.fpr FORCE
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qa64 --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $@

QOSAPP_A64_LINK = clang --target=aarch64-none-elf -fuse-ld=lld -O2 -Wall -Wextra \
	  -ffreestanding -nostdlib -nostartfiles -fno-stack-protector \
	  -fno-asynchronous-unwind-tables -fno-pic -ffixed-x18 -ffixed-x27 -ffixed-x28 \
	  -DFPR_POSIX -DFPR_QOSAPP $(QOS_BASE_FLAG) -DFPR_NHARTS=$(QOSHARTS) -DFPR_SLAB_SZ=$(QOSSLAB) -DFPR_STACK_SZ=$(QOSSTACK) $(QOSCFLAGS_EXTRA) \
	  -I$(FRUNTIME) -I$(QOS)/appside \
	  -T $(QOS)/appside/link-qosapp-a64.ld -Wl,--emit-relocs \
	  -Wl,--defsym=_heap_start=_proc_image_end -Wl,--defsym=_heap_end=_proc_image_end \
	  $(BUILD)/qosapp-a64.s $$(cat $(BUILD)/qosapp-a64.s.units) \
	  $(QOSAPP_RT_COMMON) $(FMACHINE)/unix/ctx_a64.S

$(BUILD)/qosapp-a64.elf: $(BUILD)/qosapp-a64.s $(QOSAPP_RT_COMMON) $(FMACHINE)/unix/ctx_a64.S $(QOS)/appside/link-qosapp-a64.ld tools/mkexports.py FORCE
	$(QOSAPP_A64_LINK) -Wl,--defsym=QOS_SLOT_BASE=0 -Wl,--unresolved-symbols=ignore-all -o $(BUILD)/qosapp-a64.pre.elf
	python3 tools/mkexports.py $(BUILD)/qosapp-a64.pre.elf -o $(BUILD)/qosapp-a64-exports.s
	$(QOSAPP_A64_LINK) -Wl,--defsym=QOS_SLOT_BASE=0 $(BUILD)/qosapp-a64-exports.s -o $@
	$(QOSAPP_A64_LINK) -Wl,--defsym=QOS_SLOT_BASE=0x10000000 $(BUILD)/qosapp-a64-exports.s -o $(BUILD)/qosapp-a64.moved.elf

qos-app-a64: $(BUILD)/qosapp-a64.elf tools/mkqa.py
	@MF=$(BUILD)/qosapp-a64-gen.toml; ID=$$(basename $(SOURCE) .fpr); \
	ABIV=$$(grep -m1 'define QOS_ABI_VERSION' $(QOS)/appside/qos_abi.h | grep -o '[0-9]\+' | head -1); \
	REV=$$(cat $(BUILD)/qosapp-a64.s.abirev 2>/dev/null || echo 0); \
	printf 'name = "%s"\nid = "%s"\nentry = "n/a"\nversion = "1"\nloadMode = "process"\nabi = "%s.%s"\n' $$ID $$ID $$ABIV $$REV > $$MF; \
	python3 tools/mkqa.py $$MF $(BUILD)/qosapp-a64.elf -o $(QA_OUT) \
	  --relocatable --check-moved $(BUILD)/qosapp-a64.moved.elf --delta 0x10000000
	@echo "$(QA_OUT) built for Apple Silicon (relocatable)"

# ---- plugin .qa: a library image loaded into a RUNNING app -----------------
# (docs/2026-10-01-IMPORT-TABLE.md)  A plugin carries its own generated code,
# its own copy of the prelude and modules it was compiled with, and its module
# table (ENTRY(fpr_modtab) in link-qosplug.ld).  It is RELOCATABLE: linked at
# 0 with --emit-relocs, and the app places it in a block of its own heap.  The
# runtime it calls is the app's, reached BY NAME:
#   1. a first link leaves the runtime's symbols unresolved;
#   2. tools/mkimports.py writes a stub (a jump through a slot) per function
#      and a placeholder per data object it imports;
#   3. the real link at 0, and a second at 256 MiB that mkqa --check-moved
#      compares against the RELOC list;
#   4. mkqa writes RELOC and IMPORT.  Load it from INSIDE with Plug.attach
#      (mods/plug.fpr), or launch it with std/loader.
# It is built against no particular app: any app that exports what it imports
# loads it, and one that does not says which names are missing.
PLUGID    = $(basename $(notdir $(SOURCE)))
PLUG_OUT ?= $(PLUGID).qa
PLUG_MF   = printf 'name = "%s"\nid = "%s"\nentry = "fpr_modtab"\nversion = "1"\nloadMode = "plugin"\nabi = "%s.%s"\n' $(PLUGID) $(PLUGID) \
	  $$(grep -m1 'define QOS_ABI_VERSION' $(QOS)/appside/qos_abi.h | grep -o '[0-9]\+' | head -1) $$(cat $(1).abirev 2>/dev/null || echo 0)

PLUG_X64_LINK = gcc -O2 -Wall -Wextra -ffreestanding -nostdlib -nostartfiles -static \
	  -fno-stack-protector -fno-asynchronous-unwind-tables -fno-pic \
	  -T $(QOS)/appside/link-qosplug.ld -Wl,--build-id=none -Wl,-z,noexecstack \
	  -Wl,--no-relax -Wl,--emit-relocs -Wl,--no-warn-rwx-segments

plugin-qa-x64: fprc $(FPRISC_ROOT)/core/prelude.fpr tools/mkimports.py tools/mkqa.py
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qx64 --plugin --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $(BUILD)/plug-$(PLUGID).s
	$(PLUG_X64_LINK) -Wl,--defsym=PLUG_BASE=0 -Wl,--unresolved-symbols=ignore-all \
	  $(BUILD)/plug-$(PLUGID).s $$(cat $(BUILD)/plug-$(PLUGID).s.units) -o $(BUILD)/plug-$(PLUGID).u.elf
	python3 tools/mkimports.py --arch x64 $(BUILD)/plug-$(PLUGID).u.elf -o $(BUILD)/plug-$(PLUGID).imp.s
	$(PLUG_X64_LINK) -Wl,--defsym=PLUG_BASE=0 \
	  $(BUILD)/plug-$(PLUGID).s $$(cat $(BUILD)/plug-$(PLUGID).s.units) $(BUILD)/plug-$(PLUGID).imp.s -o $(BUILD)/plug-$(PLUGID).elf
	$(PLUG_X64_LINK) -Wl,--defsym=PLUG_BASE=0x10000000 \
	  $(BUILD)/plug-$(PLUGID).s $$(cat $(BUILD)/plug-$(PLUGID).s.units) $(BUILD)/plug-$(PLUGID).imp.s -o $(BUILD)/plug-$(PLUGID).moved.elf
	@$(call PLUG_MF,$(BUILD)/plug-$(PLUGID).s) > $(BUILD)/plug-$(PLUGID)-gen.toml
	python3 tools/mkqa.py $(BUILD)/plug-$(PLUGID)-gen.toml $(BUILD)/plug-$(PLUGID).elf -o $(PLUG_OUT) \
	  --relocatable --imports --check-moved $(BUILD)/plug-$(PLUGID).moved.elf --delta 0x10000000
	@echo "$(PLUG_OUT) built (relocatable) -- install: make -C ../qos disk-seed QAS=..."

PLUG_A64_LINK = clang --target=aarch64-none-elf -fuse-ld=lld \
	  -nostdlib -nostartfiles \
	  -T $(QOS)/appside/link-qosplug.ld -Wl,--emit-relocs

plugin-qa-a64: fprc $(FPRISC_ROOT)/core/prelude.fpr tools/mkimports.py tools/mkqa.py
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qa64 --plugin --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $(BUILD)/plug-$(PLUGID)-a64.s
	$(PLUG_A64_LINK) -Wl,--defsym=PLUG_BASE=0 -Wl,--unresolved-symbols=ignore-all \
	  $(BUILD)/plug-$(PLUGID)-a64.s $$(cat $(BUILD)/plug-$(PLUGID)-a64.s.units) -o $(BUILD)/plug-$(PLUGID)-a64.u.elf
	python3 tools/mkimports.py --arch a64 $(BUILD)/plug-$(PLUGID)-a64.u.elf -o $(BUILD)/plug-$(PLUGID)-a64.imp.s
	$(PLUG_A64_LINK) -Wl,--defsym=PLUG_BASE=0 \
	  $(BUILD)/plug-$(PLUGID)-a64.s $$(cat $(BUILD)/plug-$(PLUGID)-a64.s.units) $(BUILD)/plug-$(PLUGID)-a64.imp.s -o $(BUILD)/plug-$(PLUGID)-a64.elf
	$(PLUG_A64_LINK) -Wl,--defsym=PLUG_BASE=0x10000000 \
	  $(BUILD)/plug-$(PLUGID)-a64.s $$(cat $(BUILD)/plug-$(PLUGID)-a64.s.units) $(BUILD)/plug-$(PLUGID)-a64.imp.s -o $(BUILD)/plug-$(PLUGID)-a64.moved.elf
	@$(call PLUG_MF,$(BUILD)/plug-$(PLUGID)-a64.s) > $(BUILD)/plug-$(PLUGID)-a64-gen.toml
	python3 tools/mkqa.py $(BUILD)/plug-$(PLUGID)-a64-gen.toml $(BUILD)/plug-$(PLUGID)-a64.elf -o $(PLUG_OUT) \
	  --relocatable --imports --check-moved $(BUILD)/plug-$(PLUGID)-a64.moved.elf --delta 0x10000000
	@echo "$(PLUG_OUT) built (relocatable) -- install: make -C ../qos disk-seed QAS=..."

qos-app-a64-run: qos-app-a64
	$(MAKE) -C $(QOS) portable
	$(QOS)/qosp --yes $(QA_OUT)

qos-app-mac-object: fprc $(SOURCE) $(FPRISC_ROOT)/core/prelude.fpr
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qa64mac --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $(BUILD)/qosapp-mac.s
	clang --target=arm64-apple-macos11 -c $(BUILD)/qosapp-mac.s -o $(BUILD)/qosapp-mac.o
	@echo "emitted $(BUILD)/qosapp-mac.s (Mach-O syntax, QOS-app cells)"

# ---- which image a bare `qos-app` builds is the HOST's to say, once --------
# qos.py chose the -macos targets on Apple Silicon while check-all.sh and the
# qos/tests-host scripts said `make qos-app`, so every one of them failed
# there.  The choice lives here now; both say `qos-app` and `plugin-qa` and
# get the image this machine's qosp can run.
# by ARCHITECTURE, not by OS: the a64 rules build a freestanding AArch64 ELF with
# clang + lld, which is what qosp loads on Apple Silicon AND on arm64 Linux (a
# Pi 4).  They were named -macos and chosen only on Darwin, so on arm64 Linux
# `make qos-app` built an x86-64 image.  Only the arena BASE is macOS's own
# (QOS_SLOT_BASE, above).
ifneq ($(filter arm64 aarch64,$(shell uname -m)),)
APP_HOST = a64
else
APP_HOST = x64
endif
qos-app: qos-app-$(APP_HOST)
plugin-qa: plugin-qa-$(APP_HOST)
.PHONY: qos-app plugin-qa qos-app-x64 plugin-qa-x64 qos-app-a64 plugin-qa-a64
