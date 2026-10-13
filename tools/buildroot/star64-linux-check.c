/* SPDX-License-Identifier: MIT
 * Bounded Linux checks: no raw devices, 256 MiB RAM, one temporary 8 MiB file.
 * Cross-build with the image's compiler: -O2 -pthread -lm.
 * A pass is a sampled functional check, not exhaustive hardware certification.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define ITERATIONS 32000000u
#define BYTES (128u * 1024u * 1024u)
#define FILE_BYTES (8u * 1024u * 1024u)
#define TCP_BYTES (4u * 1024u * 1024u)
static atomic_uint_fast64_t counter;
static int listener;

static void require(int ok, const char *what) {
    if (!ok) { fprintf(stderr, "FAIL %s: %s\n", what, strerror(errno)); exit(1); }
}
static double now(void) {
    struct timespec t;
    require(clock_gettime(CLOCK_MONOTONIC, &t) == 0, "clock");
    return t.tv_sec + t.tv_nsec * 1e-9;
}
static void *cpu(void *out) {
    uint64_t x = UINT64_C(0x123456789abcdef);
    for (unsigned i = 0; i < ITERATIONS; ++i) {
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    }
    *(uint64_t *)out = x;
    return NULL;
}
static void *atomic_worker(void *unused) {
    (void)unused;
    for (unsigned i = 0; i < 500000; ++i)
        atomic_fetch_add_explicit(&counter, 1, memory_order_relaxed);
    return NULL;
}
static void transfer(int fd, void *data, size_t count, int sending, int socket) {
    unsigned char *p = data;
    while (count) {
        ssize_t n = socket ? (sending ? send(fd, p, count, MSG_NOSIGNAL) : recv(fd, p, count, 0))
                           : (sending ? write(fd, p, count) : read(fd, p, count));
        if (n < 0 && errno == EINTR) continue;
        require(n > 0, "complete transfer");
        count -= (size_t)n; p += n;
    }
}
static void *tcp_server(void *out) {
    int fd = accept(listener, NULL, NULL);
    require(fd >= 0, "accept");
    unsigned char buf[65536];
    uint64_t sum = 0;
    for (unsigned n = 0; n < TCP_BYTES / sizeof buf; ++n) {
        transfer(fd, buf, sizeof buf, 0, 1);
        for (unsigned i = 0; i < sizeof buf; ++i) sum += buf[i];
    }
    transfer(fd, &sum, sizeof sum, 1, 1);
    *(uint64_t *)out = sum;
    close(fd);
    return NULL;
}
int main(void) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    alarm(90);
    struct rlimit limit = {512u * 1024u * 1024u, 512u * 1024u * 1024u};
    require(setrlimit(RLIMIT_AS, &limit) == 0, "address-space limit");
    printf("ABI pointer_bits=%zu long_bits=%zu\n", sizeof(void *) * 8, sizeof(long) * 8);
    require(sizeof(void *) == 8 && UINT64_MAX / 3 == UINT64_C(6148914691236517205), "integer ABI");
    pthread_t threads[4];
    uint64_t hashes[4], reference;
    double one[3], four[3];
    for (int sample = 0; sample < 3; ++sample) {
        double start = now(); cpu(&reference); one[sample] = now() - start;
        start = now();
        for (int i = 0; i < 4; ++i) require(!pthread_create(&threads[i], NULL, cpu, &hashes[i]), "pthread create");
        for (int i = 0; i < 4; ++i) {
            require(!pthread_join(threads[i], NULL), "pthread join");
            require(hashes[i] == reference, "parallel integer result");
        }
        four[sample] = now() - start;
        printf("CPU sample=%d single_s=%.6f four_workers_s=%.6f throughput_ratio=%.3f hash=%016" PRIx64 "\n",
               sample, one[sample], four[sample], 4 * one[sample] / four[sample], reference);
    }
    for (int i = 0; i < 4; ++i) require(!pthread_create(&threads[i], NULL, atomic_worker, NULL), "atomic pthread");
    for (int i = 0; i < 4; ++i) require(!pthread_join(threads[i], NULL), "atomic join");
    require(atomic_load(&counter) == 2000000, "atomic counter");
    puts("PASS four-thread atomic increments=2000000");
    double pi = 0, start = now();
    for (unsigned i = 0; i < 1000000; ++i) {
        double x = (i + 0.5) / 1000000.0;
        pi += 4.0 / (1.0 + x * x);
    }
    pi /= 1000000;
    require(fabs(pi - acos(-1.0)) < 1e-10 && fabs(sqrt(2.0) * sqrt(2.0) - 2.0) < 1e-12, "double precision");
    printf("PASS floating point pi=%.15f elapsed_s=%.6f\n", pi, now() - start);
    uint64_t *a = malloc(BYTES), *b = malloc(BYTES);
    require(a && b, "256 MiB allocation");
    size_t words = BYTES / sizeof *a;
    start = now();
    for (unsigned pattern = 0; pattern < 3; ++pattern) {
        for (size_t i = 0; i < words; ++i)
            a[i] = pattern == 0 ? UINT64_MAX : pattern == 1 ? UINT64_C(0xaaaaaaaa55555555) : i ^ UINT64_C(0x5aa51234fedc9876);
        memcpy(b, a, BYTES);
        for (size_t i = 0; i < words; ++i) {
            uint64_t wanted = pattern == 0 ? UINT64_MAX : pattern == 1 ? UINT64_C(0xaaaaaaaa55555555) : i ^ UINT64_C(0x5aa51234fedc9876);
            require(a[i] == wanted && b[i] == wanted, "RAM pattern/readback");
        }
    }
    printf("PASS RAM 256_MiB three_patterns elapsed_s=%.6f\n", now() - start);
    char path[] = "/root/star64-linux-check-XXXXXX";
    int fd = mkstemp(path);
    require(fd >= 0, "temporary SD filesystem file");
    start = now(); transfer(fd, a, FILE_BYTES, 1, 0);
    require(fsync(fd) == 0, "filesystem fsync");
    double write_s = now() - start;
    require(lseek(fd, 0, SEEK_SET) == 0, "file rewind");
    memset(b, 0, FILE_BYTES); transfer(fd, b, FILE_BYTES, 0, 0);
    require(!memcmp(a, b, FILE_BYTES), "filesystem byte readback");
    require(close(fd) == 0 && unlink(path) == 0, "temporary file cleanup");
    printf("PASS SD filesystem 8_MiB fsync_write_s=%.6f byte_readback (read may be cached)\n", write_s);
    listener = socket(AF_INET, SOCK_STREAM, 0);
    require(listener >= 0, "TCP socket");
    struct sockaddr_in addr = {.sin_family=AF_INET, .sin_addr.s_addr=htonl(INADDR_LOOPBACK)};
    require(!bind(listener, (struct sockaddr *)&addr, sizeof addr) && !listen(listener, 1), "TCP bind/listen");
    socklen_t len = sizeof addr;
    require(!getsockname(listener, (struct sockaddr *)&addr, &len), "TCP address");
    uint64_t server_sum, wanted_sum = 0, reply;
    for (unsigned i = 0; i < TCP_BYTES; ++i) wanted_sum += ((unsigned char *)a)[i];
    require(!pthread_create(&threads[0], NULL, tcp_server, &server_sum), "TCP server thread");
    fd = socket(AF_INET, SOCK_STREAM, 0);
    require(fd >= 0 && !connect(fd, (struct sockaddr *)&addr, len), "TCP connect");
    transfer(fd, a, TCP_BYTES, 1, 1); transfer(fd, &reply, sizeof reply, 0, 1);
    close(fd); pthread_join(threads[0], NULL); close(listener);
    require(reply == wanted_sum && server_sum == wanted_sum, "TCP data checksum");
    puts("PASS TCP loopback 4_MiB checksum");
    struct rusage usage;
    require(!getrusage(RUSAGE_SELF, &usage), "resource usage");
    printf("MEMORY peak_RSS_KiB=%ld\n", usage.ru_maxrss);
    free(a); free(b);
    puts("STAR64_LINUX_CHECK_PASS");
    return 0;
}
