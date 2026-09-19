#!/bin/sh

# blkraw-check.sh -- stage-1 disk tier verification (see blkraw_check.c).
# Persistence is a two-boot property, so the harness runs twice on one
# file; format interop is proven against a real mkdisk.py image.

set -e
cd "$(dirname "$0")"

# hostlog stub so the harness doesn't pull the sink machinery
cat > /tmp/hostlog_stub.c <<'EOF'
#include <stdarg.h>
#include <stdio.h>
void qos_hostlog(const char *fmt, ...) {
  va_list ap; va_start(ap, fmt);
  fprintf(stderr, "  [host] "); vfprintf(stderr, fmt, ap); fputc('\n', stderr);
  va_end(ap);
}
EOF

gcc -O2 -Wall -Wextra -I../../hal/unix ../../hal/unix/blk_raw.c \
    /tmp/hostlog_stub.c blkraw_check.c -o /tmp/blkraw_check -lpthread

rm -f /tmp/qdisk-test.disk
FPR_DISK=/tmp/qdisk-test.disk /tmp/blkraw_check boot1
FPR_DISK=/tmp/qdisk-test.disk /tmp/blkraw_check boot2

# a seeded image: fake .qa payloads are fine, the walk is format-level
printf 'fake-qa-one' > /tmp/one.qa
printf 'fake-qa-two-with-more-bytes' > /tmp/two.qa
python3 ../../tools/mkdisk.py /tmp/qdisk-seeded.disk 4 /tmp/one.qa /tmp/two.qa
FPR_DISK=/tmp/qdisk-seeded.disk /tmp/blkraw_check seeded

echo "blkraw-check: ALL LEGS PASS"
