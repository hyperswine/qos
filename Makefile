# QOS application builds consume FP-RISC through FPRISC_ROOT.
.DEFAULT_GOAL := all
include dependency.mk
HAL = hal
QOS = qos
BUILD ?= build
PROG ?= tests/hello.fpr
SOURCE = $(if $(wildcard $(PROG)),$(PROG),$(FPRISC_ROOT)/$(PROG))
QA_OUT ?= app.qa
QOSSLAB ?= 32768
QOSSTACK ?= 262144
QOSCFLAGS_EXTRA ?=
all: fpr
.PHONY: all fpr fprc bare-metal bare-metal-run stdcheck sol clean FORCE
fpr:
ifeq ($(wildcard .installed),)
	$(MAKE) -C "$(FPRISC_ROOT)" fpr
else
	@test -x "$(FPRC)"
endif
fprc: fpr
# a bare-metal image built FROM THIS TREE is the compiler's machine layer plus
# QOS Native's devices (hal/virt); the compiler tree alone has no drivers
QOS_HAL := $(abspath hal)
include hal/virt/qos-virt.mk
bare-metal bare-metal-run: fpr $(QOS_VIRT_HAL)
	$(MAKE) -C "$(FPRISC_ROOT)" $@ EXTRA_RT="$(abspath $(QOS_VIRT_HAL))" PROG="$(abspath $(SOURCE))" BUILD="$(abspath $(BUILD))" IMAGE="$(abspath $(if $(IMAGE),$(IMAGE),image.elf))" $(if $(HARTS),HARTS=$(HARTS)) $(if $(RVV),RVV=$(RVV))
stdcheck: fpr
	"$(FPRC)" stdcheck "$(if $(FILE),$(FILE),$(FPRISC_ROOT)/std/checkdemo.fpr)"
sol: fpr
	@echo "Use $(FPRC) sol <script>"
clean:
	rm -rf build image.elf app.qa
FORCE:
include qos-app.mk
