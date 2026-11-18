# qos-virt.mk -- QOS Native's HAL on the virt board, for every Makefile that links it.
#
# The compiler tree's machine layer is what the RUNTIME needs (boot, context
# switch, a console byte, the doorbell and timer, register access).  These are
# the DEVICES a program sees, and devices are QOS's: the PLIC (irq routing to
# the actor that bound a source), virtio net (with its TCP stack) and block,
# the pin bus, and the table that names them (generated from the board
# manifest, docs/2026-11-18-DEVICE-CLASSES.md).  docs/2026-09-19-HAL.md.
#
# Include AFTER defining FPRC, BUILD and QOS_HAL (this tree's hal/ directory);
# add $(QOS_VIRT_HAL) to the link's inputs and prerequisites.  The PLIC driver
# is FP-RISC over typed layouts, a raw library unit (rv64; plic.c is the rv32
# fallback and is empty on rv64).
SOL ?= sol
QOS_HAL_TOOLS := $(QOS_HAL)/../tools
# rv32 (XLEN=32) has no raw-unit lowering: plic.c, virtio32.c and net.c's C
# transport stand in, and these units are not built.
ifeq ($(XLEN),32)
QOS_VIRT_ASM :=
else
QOS_VIRT_ASM := $(addprefix $(BUILD)/qos-,plic.s virtio.s blockpolicy.s netpolicy.s)
endif
$(addprefix $(BUILD)/qos-,plic.s virtio.s blockpolicy.s netpolicy.s): $(BUILD)/qos-%.s: $(QOS_HAL)/virt/%.fpr $(FPRC) $(QOS_HAL_TOOLS)/build-virt-hal.sol $(QOS_HAL_TOOLS)/virt-hal.sol
	@mkdir -p "$(BUILD)"
	"$(SOL)" "$(QOS_HAL_TOOLS)/build-virt-hal.sol" "$(FPRC)" "$(QOS_HAL)" "$(BUILD)" "$*"

# The device table and the class and driver sources come from the board
# manifest (bsp/$(QOS_BOARD)/board.json) through tools/board.sol; a driver is
# plugged in there, not here.
QOS_BOARD ?= virt
QOS_BOARD_DIR := $(BUILD)/board-$(QOS_BOARD)
$(QOS_BOARD_DIR)/board.mk $(QOS_BOARD_DIR)/devtable.c: $(QOS_HAL)/../bsp/$(QOS_BOARD)/board.json $(wildcard $(QOS_HAL)/drivers/*.json) $(QOS_HAL_TOOLS)/board.sol
	cd "$(QOS_HAL)/.." && "$(SOL)" tools/board.sol bsp/$(QOS_BOARD)/board.json "$(abspath $(QOS_BOARD_DIR))"
-include $(QOS_BOARD_DIR)/board.mk

QOS_VIRT_HAL = $(QOS_VIRT_ASM) $(QOS_HAL)/virt/plic.c $(QOS_HAL)/virt/virtio32.c $(QOS_HAL)/virt/pins.c $(QOS_HAL)/core/lifecycle.c \
               $(QOS_BOARD_SOURCES) $(QOS_BOARD_DIR)/devtable.c
