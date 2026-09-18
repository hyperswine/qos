# FPRISC_ROOT names the external language checkout; no source links are created.
QOS_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ifneq ($(wildcard $(QOS_ROOT)/.installed),)
override FPRISC_ROOT := $(QOS_ROOT)/toolchain
endif
ifeq ($(strip $(FPRISC_ROOT)),)
$(error Set FPRISC_ROOT to the fprisc checkout)
endif
FPRISC_ROOT := $(abspath $(FPRISC_ROOT))
ifeq ($(wildcard $(FPRISC_ROOT)/compiler/Main.hs),)
$(error FPRISC_ROOT does not name a complete fprisc checkout)
endif
export FPRISC_ROOT
export FPR_HOME := $(QOS_ROOT)/fp-risc
export FPR_PATH := $(FPRISC_ROOT)
FPRC := $(FPRISC_ROOT)/fpr
FHAL := $(FPRISC_ROOT)/hal
