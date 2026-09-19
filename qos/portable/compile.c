/* compile.c -- qosp's UNIX-DOMAIN-SOCKET bridge to the host-side fpr
 * compiler server (tools/fprd.py).
 *
 * The app never sees a socket: it calls Sys.compile (std/compile.fpr),
 * the app-side shim rides the syscall channel with tag 7 (store.c
 * routes here), and THIS file does the host part -- connect to the
 * daemon, frame the request, stream the reply back into the channel's
 * out buffer.  The compiler stays a host process (GHC-built ./fprc
 * behind the daemon); QOS keeps the policy: what to compile, when,
 * and where the returned assembly is stored (the app writes it to
 * qosp.disk with mods/qlog like any other file).
 *
 *   socket   $FPRD_SOCK, else /tmp/fprd.sock
 *   frame    4-byte LE length + payload, both directions
 *   request  "<profile>\n<source>" (passed through verbatim; the
 *            daemon whitelists the profile token)
 *   reply    "ok\n<asm>" | "err\n<message>" -- copied verbatim into
 *            out, the app-side shim parses the status line
 *
 * Returns the reply byte count, or: -2 daemon unreachable ("no
 * compiler server"), -4 reply larger than outcap (honest refusal --
 * a truncated .s must never look compiled), -1 other socket errors. */
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static int rd_exact(int fd, void *dst, size_t n) {
  char *p = (char *)dst;
  while (n) {
    ssize_t r = read(fd, p, n);
    if (r <= 0) {
      if (r < 0 && errno == EINTR) continue;
      return -1;
    }
    p += r;
    n -= (size_t)r;
  }
  return 0;
}

static int wr_all(int fd, const void *src, size_t n) {
  const char *p = (const char *)src;
  while (n) {
    ssize_t r = write(fd, p, n);
    if (r <= 0) {
      if (r < 0 && errno == EINTR) continue;
      return -1;
    }
    p += r;
    n -= (size_t)r;
  }
  return 0;
}

int64_t qosp_compile_call(const char *pay, uint64_t plen, char *out,
                          uint64_t outcap) {
  const char *path = getenv("FPRD_SOCK");
  if (!path || !path[0]) path = "/tmp/fprd.sock";

  int fd = socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) return -1;
  struct sockaddr_un sa;
  memset(&sa, 0, sizeof sa);
  sa.sun_family = AF_UNIX;
  if (strlen(path) >= sizeof sa.sun_path) { close(fd); return -1; }
  strcpy(sa.sun_path, path);
  if (connect(fd, (struct sockaddr *)&sa, sizeof sa)) {
    close(fd);
    return -2; /* no compiler server: the app-side shim names it */
  }

  unsigned char hdr[4] = { (unsigned char)plen, (unsigned char)(plen >> 8),
                           (unsigned char)(plen >> 16),
                           (unsigned char)(plen >> 24) };
  if (wr_all(fd, hdr, 4) || wr_all(fd, pay, plen)) { close(fd); return -1; }

  if (rd_exact(fd, hdr, 4)) { close(fd); return -1; }
  uint64_t rlen = (uint64_t)hdr[0] | ((uint64_t)hdr[1] << 8) |
                  ((uint64_t)hdr[2] << 16) | ((uint64_t)hdr[3] << 24);
  if (rlen > outcap) { close(fd); return -4; }
  if (rd_exact(fd, out, rlen)) { close(fd); return -1; }
  close(fd);
  return (int64_t)rlen;
}
