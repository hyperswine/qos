/* IPC floor reference: what a round trip costs with no scheduler, no actor
 * and no protocol - only the hardware's atomic round trip between two
 * threads on one core-pair. QOS/FP-RISC message numbers become fractions
 * of this floor instead of absolutes (docs/2026-11-06-ZERO-OVERHEAD-OS-AMENDED.md,
 * addendum item 2).
 *
 * Two modes:
 *   spin  - both threads busy-wait on atomic loads (architectural floor)
 *   parked- one thread sleeps on a condition variable (naive-blocking
 *           floor: what a mutex+signal doorbell style pays, in the same
 *           spirit as QOS Portable's doorbell before the block-spin fix)
 *
 * Build: cc -O2 -pthread ipcfloor.c -o ipcfloor && ./ipcfloor [rounds]
 * Prints nanoseconds per round trip (a request and its reply), median of
 * five repeats of `rounds` (default 2,000,000) round trips.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdatomic.h>
#include <time.h>

static _Atomic uint64_t request = 0, reply = 0;
static uint64_t rounds = 2000000;

static uint64_t now_ns(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ull + ts.tv_nsec;
}

/* ---- spin mode: the architectural floor ---- */
static void *spin_responder(void *unused) {
  (void)unused;
  uint64_t seen = 0;
  while (seen < rounds) {
    while (atomic_load_explicit(&request, memory_order_acquire) == seen)
      ; /* spin */
    atomic_store_explicit(&reply, ++seen, memory_order_release);
  }
  return NULL;
}

static uint64_t spin_round_trips(void) {
  pthread_t t;
  atomic_store(&request, 0);
  atomic_store(&reply, 0);
  pthread_create(&t, NULL, spin_responder, NULL);
  uint64_t start = now_ns();
  for (uint64_t i = 1; i <= rounds; i++) {
    atomic_store_explicit(&request, i, memory_order_release);
    while (atomic_load_explicit(&reply, memory_order_acquire) < i)
      ; /* spin */
  }
  uint64_t elapsed = now_ns() - start;
  pthread_join(t, NULL);
  return elapsed / rounds;
}

/* ---- parked mode: the naive-blocking floor ---- */
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t replied = PTHREAD_COND_INITIALIZER;
static uint64_t sent = 0, done = 0;
static int responder_done = 0;

static void *parked_responder(void *unused) {
  (void)unused;
  for (;;) {
    pthread_mutex_lock(&lock);
    while (done == sent && !responder_done)
      pthread_cond_wait(&replied, &lock); /* also woken on shutdown */
    if (responder_done) { pthread_mutex_unlock(&lock); return NULL; }
    done = sent;
    pthread_cond_signal(&replied); /* wake the sender waiting on done */
    pthread_mutex_unlock(&lock);
  }
}

static uint64_t parked_round_trips(void) {
  pthread_t t;
  sent = done = responder_done = 0;
  pthread_create(&t, NULL, parked_responder, NULL);
  uint64_t start = now_ns();
  for (uint64_t i = 0; i < rounds; i++) {
    pthread_mutex_lock(&lock);
    sent++;
    pthread_cond_signal(&replied);
    while (done < sent)
      pthread_cond_wait(&replied, &lock);
    pthread_mutex_unlock(&lock);
  }
  uint64_t elapsed = now_ns() - start;
  pthread_mutex_lock(&lock);
  responder_done = 1;
  pthread_cond_broadcast(&replied);
  pthread_mutex_unlock(&lock);
  pthread_join(t, NULL);
  return elapsed / rounds;
}

static int cmp64(const void *a, const void *b) {
  uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
  return x < y ? -1 : x > y;
}

int main(int argc, char **argv) {
  /* The parked mode pays a syscall pair per round trip, so it needs far
   * fewer rounds for the same wall time; the optional argument sizes the
   * spin mode, the parked mode runs at min(rounds, 200000). */
  uint64_t spin_rounds = argc > 1 ? strtoull(argv[1], NULL, 10) : 2000000;
  setvbuf(stdout, NULL, _IOLBF, 0);
  for (int mode = 0; mode < 2; mode++) {
    rounds = mode == 0 ? spin_rounds
                       : spin_rounds < 200000 ? spin_rounds : 200000;
    printf("mode %-7s rounds per repeat: %" PRIu64 "\n",
           mode == 0 ? "spin" : "parked", rounds);
    uint64_t samples[5];
    for (int i = 0; i < 5; i++)
      samples[i] = mode == 0 ? spin_round_trips() : parked_round_trips();
    qsort(samples, 5, sizeof samples[0], cmp64);
    printf("%-7s floor: median %" PRIu64 " ns/round-trip (min %" PRIu64
           ", max %" PRIu64 ")\n",
           mode == 0 ? "spin" : "parked", samples[2], samples[0], samples[4]);
  }
  return 0;
}
