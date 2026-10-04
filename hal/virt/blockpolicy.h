/* Allocation-free ownership policy ABI. Keep numbers in sync with the raw
 * FP-RISC transition table; tests compare against an independent reference. */
#ifndef QOS_BLOCKPOLICY_H
#define QOS_BLOCKPOLICY_H
enum blk_state {
  BLK_IDLE, BLK_HELD, BLK_ORPHAN, BLK_RECLAIMING, BLK_RESETTING, BLK_OFFLINE
};
enum blk_event {
  BLK_ACQUIRE, BLK_ABANDON, BLK_RECLAIM, BLK_RESET, BLK_FINISH,
  BLK_RECOVERY_FAILED, BLK_RELEASE, BLK_RETRY
};
extern long qos_blk_ownership(long state, long event);
extern long qos_blk_claim_step(long state, int completed, int reset_due);
#endif
