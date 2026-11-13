exports unit = case unit of
    "plic" -> "irqOpen:hal_irq_open,irqClaim:hal_irq_claim,irqAck:hal_irq_ack"
  | "virtio" -> "probe:qos_virtio_probe,probeAt:qos_virtio_probe_at,negotiate:qos_virtio_negotiate,queue:qos_virtio_queue,ready:qos_virtio_ready"
  | "blockpolicy" -> "expired:qos_blk_expired,waiting:qos_blk_waiting,resetStep:qos_blk_reset_step,budgetValid:qos_blk_budget_valid,ownership:qos_blk_ownership,claimStep:qos_blk_claim_step"
  | "netpolicy" -> "receive:qos_net_receive,emit:qos_net_emit,poll:qos_net_poll,readSize:qos_net_read_size,consume:qos_net_consume,segment:qos_net_segment,connection:qos_net_connection,close:qos_net_close"
  | _ -> error "unknown virt HAL unit: {unit}".
compile env compiler hal build unit =
  source = "{hal}/virt/{unit}.fpr"; target = "{build}/qos-{unit}.s";
  argv = [compiler,"--profile=bare-metal-builtin","--arc","--raw","--lib","--export={exports unit}",source,target];
  ProcessResult status out err = unwrap (Proc.runNow (ProcessSpec argv "" env "" 0));
  if status == 0 then Unit else error "compiling {source}: {out}{err}".
