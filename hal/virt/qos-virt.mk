# qos-virt.mk -- QOS Native's HAL on the virt board, for every Makefile that links it.
#
# The compiler tree's machine layer is what the RUNTIME needs (boot, context
# switch, a console byte, the doorbell and timer, register access).  These are
# the DEVICES a program sees, and devices are QOS's: the PLIC (irq routing to
# the actor that bound a source), virtio net (with its TCP stack) and block,
# the pin bus, and the table that names them.  docs/2026-09-19-HAL.md.
#
# Include AFTER defining FPRC, BUILD and QOS_HAL (this tree's hal/ directory);
# add $(QOS_VIRT_HAL) to the link's inputs and prerequisites.  The PLIC driver
# is FP-RISC over typed layouts, a raw library unit (rv64; plic.c is the rv32
# fallback and is empty on rv64).
SOL ?= sol
QOS_HAL_TOOLS := $(QOS_HAL)/../tools
QOS_VIRT_ASM := $(addprefix $(BUILD)/qos-,plic.s virtio.s blockpolicy.s netpolicy.s)
$(QOS_VIRT_ASM): $(BUILD)/qos-%.s: $(QOS_HAL)/virt/%.fpr $(FPRC) $(QOS_HAL_TOOLS)/build-virt-hal.sol $(QOS_HAL_TOOLS)/virt-hal.sol
	@mkdir -p "$(BUILD)"
	"$(SOL)" "$(QOS_HAL_TOOLS)/build-virt-hal.sol" "$(FPRC)" "$(QOS_HAL)" "$(BUILD)" "$*"

QOS_VIRT_HAL = $(QOS_VIRT_ASM) $(QOS_HAL)/virt/plic.c $(QOS_HAL)/virt/net.c $(QOS_HAL)/net_actor_bridge.c \
               $(QOS_HAL)/virt/blk.c $(QOS_HAL)/virt/pins.c $(QOS_HAL)/virt/devices.c $(QOS_HAL)/core/lifecycle.c
