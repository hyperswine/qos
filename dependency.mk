# Where the fprisc checkout is -- the rule qos.py applies, for make run
# directly: $FPRISC_ROOT, else fprisc.path (`./qos.py fprisc DIR` writes
# it), else a sibling ../fprisc.  An installed tree ships its own.
QOS_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ifneq ($(wildcard $(QOS_ROOT)/.installed),)
override FPRISC_ROOT := $(QOS_ROOT)/toolchain
endif
ifeq ($(strip $(FPRISC_ROOT)),)
FPRISC_ROOT := $(strip $(shell cat $(QOS_ROOT)/fprisc.path 2>/dev/null))
endif
ifeq ($(strip $(FPRISC_ROOT)),)
FPRISC_ROOT := $(QOS_ROOT)/../fprisc
endif
FPRISC_ROOT := $(abspath $(FPRISC_ROOT))
ifeq ($(wildcard $(FPRISC_ROOT)/compiler/Main.hs),)
$(error no fprisc checkout at $(FPRISC_ROOT): ./qos.py fprisc /path/to/fprisc, or export FPRISC_ROOT)
endif
export FPRISC_ROOT
export FPR_HOME := $(QOS_ROOT)
export FPR_PATH := $(FPRISC_ROOT)
FPRC := $(FPRISC_ROOT)/fpr
FHAL := $(FPRISC_ROOT)/hal
