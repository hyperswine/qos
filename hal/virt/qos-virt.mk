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
QOS_PLIC_EXPORTS = irqOpen:hal_irq_open,irqClaim:hal_irq_claim,irqAck:hal_irq_ack

$(BUILD)/qos-plic.s: $(QOS_HAL)/virt/plic.fpr $(FPRC)
	@mkdir -p $(BUILD)
	"$(FPRC)" --profile=bare-metal-builtin --arc --raw --lib --export=$(QOS_PLIC_EXPORTS) $< $@ >/dev/null

QOS_VIRT_HAL = $(BUILD)/qos-plic.s $(QOS_HAL)/virt/plic.c $(QOS_HAL)/virt/net.c \
               $(QOS_HAL)/virt/blk.c $(QOS_HAL)/virt/pins.c $(QOS_HAL)/virt/devices.c

# Both device drivers share allocation-free probe/feature/queue policy on RV64.
QOS_VIRTIO_EXPORTS = probe:qos_virtio_probe,probeAt:qos_virtio_probe_at,negotiate:qos_virtio_negotiate,queue:qos_virtio_queue,ready:qos_virtio_ready
$(BUILD)/qos-virtio.s: $(QOS_HAL)/virt/virtio.fpr $(FPRC)
	@mkdir -p $(BUILD)
	"$(FPRC)" --profile=bare-metal-builtin --arc --raw --lib --export=$(QOS_VIRTIO_EXPORTS) $< $@ >/dev/null
QOS_VIRT_HAL += $(BUILD)/qos-virtio.s

$(BUILD)/qos-blockpolicy.s: $(QOS_HAL)/virt/blockpolicy.fpr $(FPRC)
	@mkdir -p $(BUILD)
	"$(FPRC)" --profile=bare-metal-builtin --arc --raw --lib --export=expired:qos_blk_expired,waiting:qos_blk_waiting,resetStep:qos_blk_reset_step $< $@ >/dev/null
QOS_VIRT_HAL += $(BUILD)/qos-blockpolicy.s
