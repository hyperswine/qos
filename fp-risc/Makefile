# QOS application builds consume FP-RISC through FPRISC_ROOT.
.DEFAULT_GOAL := all
include ../dependency.mk
HAL = ../hal
QOS = ../qos
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
ifeq ($(wildcard ../.installed),)
	$(MAKE) -C "$(FPRISC_ROOT)" fpr
else
	@test -x "$(FPRC)"
endif
fprc: fpr
bare-metal bare-metal-run: fpr
	$(MAKE) -C "$(FPRISC_ROOT)" $@ PROG="$(abspath $(SOURCE))" BUILD="$(abspath $(BUILD))" IMAGE="$(abspath $(if $(IMAGE),$(IMAGE),image.elf))" $(if $(HARTS),HARTS=$(HARTS)) $(if $(RVV),RVV=$(RVV))
stdcheck: fpr
	"$(FPRC)" stdcheck "$(if $(FILE),$(FILE),$(FPRISC_ROOT)/std/checkdemo.fpr)"
sol: fpr
	@echo "Use $(FPRC) sol <script>"
clean:
	rm -rf build image.elf app.qa
FORCE:
include qos-app.mk
