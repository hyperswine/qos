/* Companion to epbench.fpr: acknowledge and discard one machine-word write.
 * Build: cc -O2 tests/epbench_syscall.c -o /tmp/epbench_syscall
 * The descriptor stays open across the measured loop, like the held endpoint.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static uint64_t now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(EXIT_FAILURE);
    }
    return (uint64_t)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static void writes(int fd, intptr_t count) {
    for (; count > 0; --count) {
        ssize_t n;
        do {
            n = write(fd, &count, sizeof(count));
        } while (n < 0 && errno == EINTR);
        if (n != (ssize_t)sizeof(count)) {
            if (n < 0) perror("write");
            else fputs("short write to /dev/null\n", stderr);
            exit(EXIT_FAILURE);
        }
    }
}

int main(void) {
    int fd = open("/dev/null", O_WRONLY);
    if (fd < 0) {
        perror("open");
        return EXIT_FAILURE;
    }
    writes(fd, 1000);
    uint64_t start = now_ns();
    writes(fd, 20000);
    uint64_t elapsed = now_ns() - start;
    printf("epbench: held /dev/null write %.1f ns per write\n", elapsed / 20000.0);
    if (close(fd) != 0) {
        perror("close");
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
