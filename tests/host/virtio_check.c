/* Independent C reference of the pre-migration register programming.
 * Fake MMIO tests the raw C ABI without requiring a particular QEMU slot. */
#include "fpr.h"
#include "../../hal/virt/virtio.h"
static uint32_t banks[8][1024], expected[1024];
static unsigned char queue_memory[8192] __attribute__((aligned(4096)));
#define CHECK(test) do { if (!(test)) return TAG(__LINE__); } while (0)
static void clear(void) {
  for (int i = 0; i < 8; i++) for (int j = 0; j < 1024; j++) banks[i][j] = 0;
  for (int j = 0; j < 1024; j++) expected[j] = 0;
}
static void reference_features(uint32_t *r, unsigned mask) {
  r[0x70/4] = 1; r[0x70/4] = 3;
  r[0x14/4] = 0; r[0x24/4] = 0; r[0x20/4] = r[0x10/4] & mask;
  if (r[1] == 2) {
    r[0x14/4] = 1; r[0x24/4] = 1; r[0x20/4] = r[0x10/4] & 1;
    r[0x70/4] = 11;
  } else r[0x28/4] = 4096;
}
static int reference_queue(uint32_t *r, int index, int size, uintptr_t memory) {
  r[0x30/4] = index;
  if (size <= 0 || r[0x34/4] < (unsigned)size) return 0;
  r[0x38/4] = size;
  if (r[1] == 1) { r[0x3c/4] = 4096; r[0x40/4] = memory >> 12; }
  else {
    uintptr_t addresses[] = {memory, memory + size * 16, memory + 4096};
    int offsets[] = {0x80, 0x90, 0xa0};
    for (int i = 0; i < 3; i++) {
      r[offsets[i]/4] = addresses[i]; r[offsets[i]/4+1] = addresses[i] >> 32;
    }
    r[0x44/4] = 1;
  }
  return 1;
}
static int same(void) {
  for (int j = 0; j < 1024; j++) if (banks[0][j] != expected[j]) return 0;
  return 1;
}
static V check(V unit) {
  (void)unit; clear();
  CHECK(!qos_virtio_probe_at(banks, 8, 4096, 2));
  banks[0][0] = banks[1][0] = banks[7][0] = 0x74726976;
  banks[0][1] = 3; banks[0][2] = 2; /* unsupported version */
  banks[1][1] = 1; banks[1][2] = 1; /* wrong device */
  banks[7][1] = 2; banks[7][2] = 2;
  CHECK(qos_virtio_probe_at(banks, 8, 4096, 2) == banks[7]);
  CHECK(qos_virtio_probe_at(banks, 8, 4096, 1) == banks[1]);
  CHECK(!qos_virtio_probe_at(banks, 0, 4096, 1));
  for (int version = 1; version <= 2; version++) {
    for (int mask = 0; mask <= 32; mask += 32) {
      clear(); banks[0][1] = expected[1] = version;
      banks[0][4] = expected[4] = 0x21;
      reference_features(expected, mask);
      CHECK(qos_virtio_negotiate(banks[0], mask) == 1); CHECK(same());
      qos_virtio_ready(banks[0]); expected[0x70/4] = version == 2 ? 15 : 7; CHECK(same());
    }
    for (int max = 0; max <= 8; max += 4) for (int qi = 0; qi <= 1; qi++) {
      clear(); banks[0][1] = expected[1] = version;
      banks[0][0x34/4] = expected[0x34/4] = max;
      int want = reference_queue(expected, qi, 8, (uintptr_t)queue_memory);
      CHECK(qos_virtio_queue(banks[0], qi, 8, queue_memory) == want); CHECK(same());
    }
    clear(); banks[0][1] = expected[1] = version;
    CHECK(qos_virtio_queue(banks[0], 0, 0, queue_memory) == 0); CHECK(same());
    /* Modern address splitting must preserve nonzero high words. No DMA. */
    if (version == 2) {
      banks[0][0x34/4] = expected[0x34/4] = 8;
      uintptr_t high = 0x123456780000ULL;
      reference_queue(expected, 1, 8, high);
      CHECK(qos_virtio_queue(banks[0], 1, 8, (void *)high) == 1); CHECK(same());
    }
  }
  /* Full-word clocks, wrap, unavailable clock and fallback park budgets. */
  uint64_t edges[] = {0, 1, 1999, 2000, 3000000, (1ULL<<62)-1,
                       1ULL<<62, 1ULL<<63, UINT64_MAX};
  for (unsigned i = 0; i < sizeof edges / sizeof *edges; i++)
    for (unsigned j = 0; j < sizeof edges / sizeof *edges; j++)
      for (unsigned k = 0; k < sizeof edges / sizeof *edges; k++) {
        uint64_t since = edges[i], now = edges[j], ticks = edges[k];
        uint64_t elapsed = since && now ? now - since : 0;
        uint64_t parks = edges[j], limit = edges[k];
        int want = since ? elapsed >= ticks : parks >= limit;
        CHECK(qos_blk_expired(since, now, ticks, parks, limit) == want);
      }
  return TAG(0);
}
FPR_FN(fpr_g_virtioCheck, check, 1);
