/* virtio32.c -- the rv32 virtio-mmio setup and block policy.
 *
 * On rv64 these are virtio.fpr and blockpolicy.fpr: FP-RISC raw library units
 * whose exports are the C symbols in virtio.h and blockpolicy.h. The raw ABI
 * has no rv32 lowering, so an rv32 image keeps this C, written from those
 * units line by line (as plic.c is for plic.fpr); on rv64 this file is empty.
 * tests/host/virtio_check.c is the independent reference both are held to. */
#include "fpr.h"
#if __riscv_xlen == 32
#include "virtio.h"
#include "blockpolicy.h"

static uint32_t rd(volatile uint32_t *base, unsigned off) {
  __asm__ volatile("fence" ::: "memory");
  uint32_t v = base[off / 4];
  __asm__ volatile("fence" ::: "memory");
  return v;
}
static void wr(volatile uint32_t *base, unsigned off, uint32_t v) {
  __asm__ volatile("fence" ::: "memory");
  base[off / 4] = v;
  __asm__ volatile("fence" ::: "memory");
}

volatile uint32_t *qos_virtio_probe_at(void *base, long slots, long stride, long device) {
  for (long i = 0; i < slots; i++) {
    volatile uint32_t *at = (volatile uint32_t *)((uintptr_t)base + (uintptr_t)(i * stride));
    if (rd(at, 0) == 0x74726976u && rd(at, 8) == (uint32_t)device) {
      uint32_t version = rd(at, 4);
      if (version == 1 || version == 2) return at;
    }
  }
  return 0;
}
volatile uint32_t *qos_virtio_probe(long device) {
  return qos_virtio_probe_at((void *)0x10001000u, 8, 4096, device);
}

/* Reset is separate: recovery must confirm reset before reusing DMA memory. */
long qos_virtio_negotiate(volatile uint32_t *base, uintptr_t low_mask) {
  wr(base, 112, 1);
  wr(base, 112, 3);
  wr(base, 20, 0);
  uint32_t low = rd(base, 16);
  wr(base, 36, 0);
  wr(base, 32, low & (uint32_t)low_mask);
  if (rd(base, 4) != 2) { wr(base, 40, 4096); return 1; }
  wr(base, 20, 1);
  uint32_t high = rd(base, 16);
  wr(base, 36, 1);
  wr(base, 32, high & 1);
  wr(base, 112, 11);
  return (rd(base, 112) >> 3) & 1;
}

/* desc + avail in the first page, used in the second; the caller clears it */
long qos_virtio_queue(volatile uint32_t *base, long index, long size, void *memory) {
  wr(base, 48, (uint32_t)index);
  if (!(size > 0 && (long)rd(base, 52) >= size)) return 0;
  wr(base, 56, (uint32_t)size);
  uintptr_t m = (uintptr_t)memory;
  if (rd(base, 4) == 1) {
    wr(base, 60, 4096);
    wr(base, 64, (uint32_t)(m >> 12));
  } else {
    wr(base, 128, (uint32_t)m);                 wr(base, 132, 0);
    wr(base, 144, (uint32_t)(m + (uintptr_t)size * 16)); wr(base, 148, 0);
    wr(base, 160, (uint32_t)(m + 4096));        wr(base, 164, 0);
    wr(base, 68, 1);
  }
  return 1;
}
void qos_virtio_ready(volatile uint32_t *base) { wr(base, 112, rd(base, 4) == 2 ? 15 : 7); }

/* ---- block policy (blockpolicy.fpr) ---- */
long qos_blk_expired(uint64_t since, uint64_t now, uint64_t ticks, uint64_t parks, uint64_t park_limit) {
  if (since == 0) return parks >= park_limit;
  return (now == 0 ? 0 : now - since) >= ticks;
}
/* state 2 orphan; command 0 park, 1 reclaim, 2 reset, 3 refuse wait */
long qos_blk_waiting(long state, int completed, int reset_due, int wait_due) {
  if (state == 2) return completed ? 1 : reset_due ? 2 : 0;
  return wait_due ? 3 : 0;
}
/* 0 park, 1 confirmed reset, 2 reset budget exhausted */
long qos_blk_reset_step(uintptr_t status, long attempt, long limit) {
  if (attempt >= limit) return 2;
  return status == 0 ? 1 : 0;
}
long qos_blk_budget_valid(long us, long probes, long factor) {
  return us >= 1 && us <= 60000000 && probes >= 1 && probes <= 100000 && factor >= 1 && factor <= 64;
}
long qos_blk_ownership(long state, long event) {
  if (event < 0 || event > 7 || state < 0 || state > 5) return state >= 0 && state <= 5 ? state : 5;
  switch (state * 8 + event) {
  case 0 * 8 + 0: return 1;
  case 1 * 8 + 1: return 2;
  case 2 * 8 + 2: return 3;
  case 2 * 8 + 3: return 4;
  case 3 * 8 + 4: return 0;
  case 3 * 8 + 5: return 5;
  case 4 * 8 + 4: return 0;
  case 4 * 8 + 5: return 5;
  case 1 * 8 + 6: return 0;
  case 3 * 8 + 7: return 2;
  case 4 * 8 + 7: return 2;
  default: return state >= 0 && state <= 5 ? state : 5;
  }
}
long qos_blk_claim_step(long state, int completed, int reset_due) {
  if (state == 3) return completed ? 1 : 0;
  if (state == 4) return completed ? 0 : reset_due ? 2 : 0;
  return 0;
}
#endif
