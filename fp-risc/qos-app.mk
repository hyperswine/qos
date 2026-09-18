# ---- QOSPortable profile: the app side ---------------------------------
# The .qa is freestanding at the published slot; every effect goes
# through the qos_hal_t table (qos/appside/hal.c).  The HOST is built
# separately: make -C ../qos portable.
QOS_SLOT_BASE  = 0x400000000
# the app's notion of "the heap" (fpr_in_heap) ends where the host's
# arena ends: MUST agree with qos/Makefile's ARENA_MB, or a grant above
# the line is mistaken for a static and shared by identity (found as
# random corruption past ~220 sessions when the host arena grew to 2 GiB)
ARENA_MB ?= 2048
PROC_ARENA_END := $(shell printf '0x%x' $$(( $(QOS_SLOT_BASE) + $(ARENA_MB) * 1048576 )))
QOSHARTS ?= 8
QOSAPP_RT_COMMON = $(QOS)/appside/entry.c $(QOS)/appside/hal.c $(QOS)/appside/support.c \
				   $(FHAL)/core/runtime.c $(FHAL)/core/actors.c $(FHAL)/core/bits.c \
				   $(FHAL)/core/vec.c $(FHAL)/core/sstr.c $(FHAL)/core/mod.c \
				   $(FHAL)/core/buddy.c
QOSAPP_RT = $(QOSAPP_RT_COMMON) $(FHAL)/unix/ctx_x64.S

$(BUILD)/qosapp-prog.s: fprc $(SOURCE) $(FPRISC_ROOT)/core/prelude.fpr FORCE
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --profile=qos-portable --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $@

$(BUILD)/qosapp.elf: $(BUILD)/qosapp-prog.s $(QOSAPP_RT) $(QOS)/appside/link-qosapp.ld
	gcc -O2 -Wall -Wextra -ffreestanding -nostdlib -nostartfiles -static \
	  -fno-stack-protector -fno-asynchronous-unwind-tables -fno-pic -mcmodel=large \
	  -DFPR_POSIX -DFPR_QOSAPP -DFPR_NHARTS=$(QOSHARTS) -DFPR_SLAB_SZ=$(QOSSLAB) -DFPR_STACK_SZ=$(QOSSTACK) $(QOSCFLAGS_EXTRA) \
	  -I$(FHAL)/core -I$(QOS)/appside \
	  -T $(QOS)/appside/link-qosapp.ld -Wl,--defsym=QOS_SLOT_BASE=$(QOS_SLOT_BASE) \
	  -Wl,--defsym=_heap_start=_proc_image_end -Wl,--defsym=_heap_end=_proc_image_end \
	  -Wl,--defsym=_proc_arena_end=$(PROC_ARENA_END) \
	  -Wl,--build-id=none -Wl,-z,noexecstack \
	  $(BUILD)/qosapp-prog.s $$(cat $(BUILD)/qosapp-prog.s.units) $(QOSAPP_RT) -o $@

qos-app: $(BUILD)/qosapp.elf tools/mkqa.py
	@MF=$(BUILD)/qosapp-gen.toml; ID=$$(basename $(SOURCE) .fpr); \
	ABIV=$$(grep -m1 'define QOS_ABI_VERSION' $(QOS)/appside/qos_abi.h | grep -o '[0-9]\+' | head -1); \
	REV=$$(cat $(BUILD)/qosapp-prog.s.abirev 2>/dev/null || echo 0); \
	printf 'name = "%s"\nid = "%s"\nentry = "n/a"\nversion = "1"\nloadMode = "process"\nabi = "%s.%s"\n' $$ID $$ID $$ABIV $$REV > $$MF; \
	python3 tools/mkqa.py $$MF $(BUILD)/qosapp.elf -o $(QA_OUT)
	@echo "$(QA_OUT) built — run with: (cd ../qos && make portable && ./qosp --yes ../fp-risc/$(QA_OUT))"

# ---- QOS app for macOS (Apple Silicon) -----------------------------------
# qosp's in-process loader consumes fixed-slot ELF on every host.  Apple
# Clang + lld can cross-link that AArch64 ELF without a Linux sysroot because
# the app and runtime are freestanding.  The code still executes under Darwin,
# where x18 is platform-reserved, so the generic ELF compiler must not use it.
# Mach-O emission remains available separately for native macOS integration work.
$(BUILD)/qosapp-a64.s: fprc $(SOURCE) $(FPRISC_ROOT)/core/prelude.fpr FORCE
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qa64 --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $@

$(BUILD)/qosapp-a64.elf: $(BUILD)/qosapp-a64.s $(QOSAPP_RT_COMMON) $(FHAL)/unix/ctx_a64.S $(QOS)/appside/link-qosapp-a64.ld
	clang --target=aarch64-none-elf -fuse-ld=lld -O2 -Wall -Wextra \
	  -ffreestanding -nostdlib -nostartfiles -fno-stack-protector \
	  -fno-asynchronous-unwind-tables -fno-pic -ffixed-x18 -ffixed-x28 \
	  -DFPR_POSIX -DFPR_QOSAPP -DFPR_NHARTS=$(QOSHARTS) -DFPR_SLAB_SZ=$(QOSSLAB) -DFPR_STACK_SZ=$(QOSSTACK) $(QOSCFLAGS_EXTRA) \
	  -I$(FHAL)/core -I$(QOS)/appside \
	  -T $(QOS)/appside/link-qosapp-a64.ld -Wl,--defsym=QOS_SLOT_BASE=$(QOS_SLOT_BASE) \
	  -Wl,--defsym=_heap_start=_proc_image_end -Wl,--defsym=_heap_end=_proc_image_end \
	  -Wl,--defsym=_proc_arena_end=$(PROC_ARENA_END) \
	  $(BUILD)/qosapp-a64.s $$(cat $(BUILD)/qosapp-a64.s.units) \
	  $(QOSAPP_RT_COMMON) $(FHAL)/unix/ctx_a64.S -o $@

qos-app-macos: $(BUILD)/qosapp-a64.elf tools/mkqa.py
	@MF=$(BUILD)/qosapp-a64-gen.toml; ID=$$(basename $(SOURCE) .fpr); \
	ABIV=$$(grep -m1 'define QOS_ABI_VERSION' $(QOS)/appside/qos_abi.h | grep -o '[0-9]\+' | head -1); \
	REV=$$(cat $(BUILD)/qosapp-a64.s.abirev 2>/dev/null || echo 0); \
	printf 'name = "%s"\nid = "%s"\nentry = "n/a"\nversion = "1"\nloadMode = "process"\nabi = "%s.%s"\n' $$ID $$ID $$ABIV $$REV > $$MF; \
	python3 tools/mkqa.py $$MF $(BUILD)/qosapp-a64.elf -o $(QA_OUT)
	@echo "$(QA_OUT) built for Apple Silicon"

# ---- plugin .qa: a library image loaded into the RUNNING shell -----------
# Linked at a PLUG sub-slot (qos_abi.h: 0x408000000 + PLUGSLOT * 4 MiB,
# 8 slots) against the running app image's OWN symbol addresses -- a
# PROVIDE() script generated from nm.  The plugin carries only its own
# generated code + module table (ENTRY(fpr_modtab) in link-qosplug.ld);
# the runtime C, prelude, and any shared mods resolve to the shell's
# copy.  Load it from INSIDE: read apps/<id>.qa off qosp.disk with
# mods/qlog, hand the bytes to Sys.attachQa (tests/qload.fpr).
#
# TWO LAWS, both previously paid for in blood:
#   1. plugin targets DELIBERATELY do not depend on the app elf -- a
#      silent shell rebuild would desync every PROVIDE address
#      (SIGSEGV pc=0).  After ANY shell rebuild: make plugsyms[-macos],
#      then rebuild EVERY plugin, then reinstall the whole set.
#   2. qosp + app.qa + all plugin .qa's install as a matched set.
PLUGSLOT ?= 0
PLUGID    = $(basename $(notdir $(SOURCE)))
PLUG_OUT ?= $(PLUGID).qa
PLUGBASE  = $(shell printf '0x%x' $$(( 0x408000000 + $(PLUGSLOT) * 4194304 )))

plugsyms:
	@test -f $(BUILD)/qosapp.elf || { echo "build the shell first: make qos-app PROG=<shell>"; exit 1; }
	nm --defined-only $(BUILD)/qosapp.elf | \
	  awk '$$2 ~ /^[A-Z]$$/ && $$3 != "" && $$3 !~ /^\$$/ { printf "PROVIDE(%s = 0x%s);\n", $$3, $$1 }' > $(BUILD)/plugsyms-x64.ld
	@echo "plugsyms-x64.ld: $$(wc -l < $(BUILD)/plugsyms-x64.ld) shell symbols"

plugsyms-macos:
	@test -f $(BUILD)/qosapp-a64.elf || { echo "build the shell first: make qos-app-macos PROG=<shell>"; exit 1; }
	nm --defined-only $(BUILD)/qosapp-a64.elf | \
	  awk '$$2 ~ /^[A-Z]$$/ && $$3 != "" && $$3 !~ /^\$$/ { printf "PROVIDE(%s = 0x%s);\n", $$3, $$1 }' > $(BUILD)/plugsyms-a64.ld
	@echo "plugsyms-a64.ld: $$(wc -l < $(BUILD)/plugsyms-a64.ld) shell symbols"

plugin-qa: fprc $(FPRISC_ROOT)/core/prelude.fpr
	@test -f $(BUILD)/plugsyms-x64.ld || { echo "no plugsyms: make plugsyms first (after the shell build)"; exit 1; }
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qx64 --plugin --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $(BUILD)/plug-$(PLUGID).s
	gcc -O2 -Wall -Wextra -ffreestanding -nostdlib -nostartfiles -static \
	  -fno-stack-protector -fno-asynchronous-unwind-tables -fno-pic -mcmodel=large \
	  -DFPR_POSIX -DFPR_QOSAPP -DFPR_NHARTS=$(QOSHARTS) -DFPR_SLAB_SZ=$(QOSSLAB) -DFPR_STACK_SZ=$(QOSSTACK) $(QOSCFLAGS_EXTRA) -I$(FHAL)/core -I$(QOS)/appside \
	  -T $(QOS)/appside/link-qosplug.ld -T $(BUILD)/plugsyms-x64.ld \
	  -Wl,--defsym=PLUG_BASE=$(PLUGBASE) -Wl,--build-id=none -Wl,-z,noexecstack \
	  $(BUILD)/plug-$(PLUGID).s $$(cat $(BUILD)/plug-$(PLUGID).s.units) -o $(BUILD)/plug-$(PLUGID).elf
	@MF=$(BUILD)/plug-$(PLUGID)-gen.toml; \
	printf 'name = "%s"\nid = "%s"\nentry = "fpr_modtab"\nversion = "1"\nloadMode = "plugin"\n' $(PLUGID) $(PLUGID) > $$MF; \
	python3 tools/mkqa.py $$MF $(BUILD)/plug-$(PLUGID).elf -o $(PLUG_OUT) --shell-of $(QA_OUT)
	@echo "$(PLUG_OUT) built at sub-slot $(PLUGSLOT) ($(PLUGBASE)) -- install: make -C ../qos disk-seed QAS=..."

plugin-qa-macos: fprc $(FPRISC_ROOT)/core/prelude.fpr
	@test -f $(BUILD)/plugsyms-a64.ld || { echo "no plugsyms: make plugsyms-macos first (after the shell build)"; exit 1; }
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qa64 --plugin --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $(BUILD)/plug-$(PLUGID)-a64.s
	clang --target=aarch64-none-elf -fuse-ld=lld -O2 -Wall -Wextra \
	  -ffreestanding -nostdlib -nostartfiles -fno-stack-protector \
	  -fno-asynchronous-unwind-tables -fno-pic -ffixed-x28 \
	  -DFPR_POSIX -DFPR_QOSAPP -DFPR_NHARTS=$(QOSHARTS) -DFPR_SLAB_SZ=$(QOSSLAB) -DFPR_STACK_SZ=$(QOSSTACK) $(QOSCFLAGS_EXTRA) -I$(FHAL)/core -I$(QOS)/appside \
	  -T $(QOS)/appside/link-qosplug.ld -T $(BUILD)/plugsyms-a64.ld \
	  -Wl,--defsym=PLUG_BASE=$(PLUGBASE) \
	  $(BUILD)/plug-$(PLUGID)-a64.s $$(cat $(BUILD)/plug-$(PLUGID)-a64.s.units) -o $(BUILD)/plug-$(PLUGID)-a64.elf
	@MF=$(BUILD)/plug-$(PLUGID)-a64-gen.toml; \
	printf 'name = "%s"\nid = "%s"\nentry = "fpr_modtab"\nversion = "1"\nloadMode = "plugin"\n' $(PLUGID) $(PLUGID) > $$MF; \
	python3 tools/mkqa.py $$MF $(BUILD)/plug-$(PLUGID)-a64.elf -o $(PLUG_OUT) --shell-of $(QA_OUT)
	@echo "$(PLUG_OUT) built at sub-slot $(PLUGSLOT) ($(PLUGBASE)) -- install: make -C ../qos disk-seed QAS=..."

qos-app-macos-run: qos-app-macos
	$(MAKE) -C $(QOS) portable
	$(QOS)/qosp --yes $(QA_OUT)

qos-app-macos-object: fprc $(SOURCE) $(FPRISC_ROOT)/core/prelude.fpr
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qa64mac --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $(BUILD)/qosapp-mac.s
	clang --target=arm64-apple-macos11 -c $(BUILD)/qosapp-mac.s -o $(BUILD)/qosapp-mac.o
	@echo "emitted $(BUILD)/qosapp-mac.s (Mach-O syntax, QOS-app cells)"
