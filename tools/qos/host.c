/* host.c -- the few host calls the `qos` command needs beyond std/os.
 *
 * Linked beside tools/qos/qos.fpr by `fpr build --with` (tools/qos/build.sh).
 * Every function here is a thin, checked wrapper: policy stays in FP-RISC.
 * SHA-256 is QOS's own implementation (qos/portable/sha256.c), included so
 * the command and the hosts hash with the same code.
 */
#include "os_value.h"
#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

#include "../../qos/portable/sha256.c"

extern char **environ;

static V unit_ok(void) { return os_ok((V)&fpr_unit); }
static const str_t *want_str(V v, const char *who) {
  if (ISINT(v) || TID(v) != T_STR) fpr_cpanic(who);
  return (const str_t *)v;
}
static V hex_of(const unsigned char d[32]) {
  static const char digits[] = "0123456789abcdef";
  char hex[64];
  for (int i = 0; i < 32; i++) { hex[2 * i] = digits[d[i] >> 4]; hex[2 * i + 1] = digits[d[i] & 15]; }
  return os_str(hex, 64);
}

/* Qos.sha256 : String -> String -- 64 lowercase hex digits */
static V h_sha256(V s) {
  const str_t *b = want_str(s, "Qos.sha256: not a String");
  unsigned char d[32];
  qosp_sha256(b->bytes, b->len, d);
  return hex_of(d);
}
FPR_FN(fpr_g_Qos_x2esha256, h_sha256, 1);

/* Qos.sha256File : String -> Result String String -- the file mapped, not copied */
static V h_sha256_file(V pathv) {
  char *path = os_cstr(pathv, "Qos.sha256File: path");
  int fd = open(path, O_RDONLY | O_CLOEXEC);
  free(path);
  if (fd < 0) return os_errno();
  struct stat st;
  if (fstat(fd, &st) || !S_ISREG(st.st_mode)) { close(fd); return os_err("not a regular file"); }
  unsigned char d[32];
  if (st.st_size == 0) {
    qosp_sha256((const unsigned char *)"", 0, d);
  } else {
    void *m = mmap(0, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (m == MAP_FAILED) { V e = os_errno(); close(fd); return e; }
    qosp_sha256(m, (uint64_t)st.st_size, d);
    munmap(m, (size_t)st.st_size);
  }
  close(fd);
  return os_ok(hex_of(d));
}
FPR_FN(fpr_g_Qos_x2esha256File, h_sha256_file, 1);

/* Qos.realpath : String -> Result String String */
static V h_realpath(V pathv) {
  char *path = os_cstr(pathv, "Qos.realpath: path");
  char out[PATH_MAX];
  char *r = realpath(path, out);
  free(path);
  if (!r) return os_errno();
  return os_ok(os_str(out, (uw)strlen(out)));
}
FPR_FN(fpr_g_Qos_x2erealpath, h_realpath, 1);

/* Qos.kind : String -> Int -- without following a final symlink:
 * -1 missing, 0 regular file, 1 directory, 2 symlink, 3 other */
static V h_kind(V pathv) {
  char *path = os_cstr(pathv, "Qos.kind: path");
  struct stat st;
  int r = lstat(path, &st);
  free(path);
  if (r) return TAG(-1);
  return TAG(S_ISREG(st.st_mode) ? 0 : S_ISDIR(st.st_mode) ? 1 : S_ISLNK(st.st_mode) ? 2 : 3);
}
FPR_FN(fpr_g_Qos_x2ekind, h_kind, 1);

/* Qos.setEnv : String -> String -> Unit; Qos.unsetEnv : String -> Unit.
 * Children (Os.run) and exec (Os.exec) inherit this process's environment. */
static V h_setenv(V namev, V valuev) {
  char *name = os_cstr(namev, "Qos.setEnv: name"), *value = os_cstr(valuev, "Qos.setEnv: value");
  if (setenv(name, value, 1)) fpr_cpanic("Qos.setEnv: invalid name");
  free(name); free(value);
  return (V)&fpr_unit;
}
FPR_FN(fpr_g_Qos_x2esetEnv, h_setenv, 2);
static V h_unsetenv(V namev) {
  char *name = os_cstr(namev, "Qos.unsetEnv: name");
  unsetenv(name);
  free(name);
  return (V)&fpr_unit;
}
FPR_FN(fpr_g_Qos_x2eunsetEnv, h_unsetenv, 1);

/* Qos.envNames : Unit -> List String */
static V h_env_names(V u) {
  (void)u;
  V l = (V)&os_nil;
  for (char **e = environ; *e; e++) {
    const char *eq = strchr(*e, '=');
    l = os_cons(os_str(*e, eq ? (uw)(eq - *e) : (uw)strlen(*e)), l);
  }
  return l;
}
FPR_FN(fpr_g_Qos_x2eenvNames, h_env_names, 1);

/* Qos.lock : String -> Result Int String -- open a regular file read-write,
 * not close-on-exec (a host started by exec takes it over: FPR_DISK_LOCK_FD),
 * and take the nonblocking exclusive inode lock hal/unix/blk_raw.c takes.
 * "in use" when another process holds it. */
static V h_lock(V pathv) {
  char *path = os_cstr(pathv, "Qos.lock: path");
  int fd = open(path, O_RDWR | O_NOFOLLOW);
  free(path);
  if (fd < 0) return os_errno();
  struct stat st;
  if (fstat(fd, &st) || !S_ISREG(st.st_mode)) { close(fd); return os_err("not a regular file"); }
  if (flock(fd, LOCK_EX | LOCK_NB) < 0) {
    int e = errno;
    close(fd);
    if (e == EWOULDBLOCK) return os_err("in use");
    errno = e;
    return os_errno();
  }
  return os_ok(TAG(fd));
}
FPR_FN(fpr_g_Qos_x2elock, h_lock, 1);

/* Qos.createSparse : String -> Int -> Result Unit String -- a new file of
 * that many bytes (refused if the name exists), unformatted */
static V h_create_sparse(V pathv, V sizev) {
  char *path = os_cstr(pathv, "Qos.createSparse: path");
  int fd = open(path, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0644);
  free(path);
  if (fd < 0) return os_errno();
  int r = ftruncate(fd, (off_t)UNTAG(sizev));
  V out = r ? os_errno() : unit_ok();
  close(fd);
  return out;
}
FPR_FN(fpr_g_Qos_x2ecreateSparse, h_create_sparse, 2);

/* Qos.tempFile : String -> Result (Int, String) String -- mkstemp in a
 * directory, locked (flock) like a disk, close-on-exec */
static V h_temp_file(V templv) {
  char *templ = os_cstr(templv, "Qos.tempFile: template");
  int fd = mkstemp(templ);
  if (fd < 0) { free(templ); return os_errno(); }
  fcntl(fd, F_SETFD, FD_CLOEXEC);
  if (flock(fd, LOCK_EX | LOCK_NB) < 0) { V e = os_errno(); close(fd); unlink(templ); free(templ); return e; }
  V f[2] = {TAG(fd), os_str(templ, (uw)strlen(templ))};
  free(templ);
  return os_ok(os_cell(T_TUP2, 0, 2, f));
}
FPR_FN(fpr_g_Qos_x2etempFile, h_temp_file, 1);

/* Qos.tempDir : String -> Result String String -- mkdtemp */
static V h_temp_dir(V templv) {
  char *templ = os_cstr(templv, "Qos.tempDir: template");
  char *r = mkdtemp(templ);
  V out = r ? os_ok(os_str(templ, (uw)strlen(templ))) : os_errno();
  free(templ);
  return out;
}
FPR_FN(fpr_g_Qos_x2etempDir, h_temp_dir, 1);

/* Qos.removeTree : String -> Unit -- best effort, never follows symlinks */
static void remove_tree(const char *path) {
  struct stat st;
  if (lstat(path, &st)) return;
  if (S_ISDIR(st.st_mode)) {
    DIR *d = opendir(path);
    if (d) {
      struct dirent *e;
      while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        size_t n = strlen(path) + strlen(e->d_name) + 2;
        char *child = malloc(n);
        if (!child) break;
        snprintf(child, n, "%s/%s", path, e->d_name);
        remove_tree(child);
        free(child);
      }
      closedir(d);
    }
    rmdir(path);
  } else {
    unlink(path);
  }
}
static V h_remove_tree(V pathv) {
  char *path = os_cstr(pathv, "Qos.removeTree: path");
  remove_tree(path);
  free(path);
  return (V)&fpr_unit;
}
FPR_FN(fpr_g_Qos_x2eremoveTree, h_remove_tree, 1);

/* Qos.pread : Int -> Int -> Int -> Result String String -- exactly n bytes */
static V h_pread(V fdv, V offv, V nv) {
  int fd = want_fd(fdv, "Qos.pread: fd");
  sw off = UNTAG(offv), n = UNTAG(nv);
  if (off < 0 || n < 0) return os_err("negative offset or size");
  char *buf = malloc(n ? (size_t)n : 1);
  if (!buf) fpr_cpanic("out of memory");
  sw got = 0;
  while (got < n) {
    ssize_t r = pread(fd, buf + got, (size_t)(n - got), (off_t)(off + got));
    if (r < 0 && errno == EINTR) continue;
    if (r <= 0) { free(buf); return r < 0 ? os_errno() : os_err("short disk read"); }
    got += r;
  }
  V s = os_str(buf, (uw)n);
  free(buf);
  return os_ok(s);
}
FPR_FN(fpr_g_Qos_x2epread, h_pread, 3);

/* Qos.pwrite : Int -> Int -> String -> Result Unit String -- all of it */
static V h_pwrite(V fdv, V offv, V bytesv) {
  int fd = want_fd(fdv, "Qos.pwrite: fd");
  const str_t *b = want_str(bytesv, "Qos.pwrite: not a String");
  sw off = UNTAG(offv);
  uw done = 0;
  while (done < b->len) {
    ssize_t w = pwrite(fd, b->bytes + done, b->len - done, (off_t)(off + (sw)done));
    if (w < 0 && errno == EINTR) continue;
    if (w <= 0) return w < 0 ? os_errno() : os_err("short disk write");
    done += (uw)w;
  }
  return unit_ok();
}
FPR_FN(fpr_g_Qos_x2epwrite, h_pwrite, 3);

/* Qos.fullSync : Int -> Result Unit String -- fsync, and on macOS F_FULLFSYNC */
static V h_full_sync(V fdv) {
  int fd = want_fd(fdv, "Qos.fullSync: fd");
  if (fsync(fd)) return os_errno();
#ifdef F_FULLFSYNC
  if (fcntl(fd, F_FULLFSYNC) < 0) return os_errno();
#endif
  return unit_ok();
}
FPR_FN(fpr_g_Qos_x2efullSync, h_full_sync, 1);

/* Qos.fdSize : Int -> Result Int String; Qos.truncate : Int -> Int -> Result Unit String */
static V h_fd_size(V fdv) {
  struct stat st;
  if (fstat(want_fd(fdv, "Qos.fdSize: fd"), &st)) return os_errno();
  return os_ok(TAG((sw)st.st_size));
}
FPR_FN(fpr_g_Qos_x2efdSize, h_fd_size, 1);
static V h_truncate(V fdv, V sizev) {
  return os_unit_or_errno(ftruncate(want_fd(fdv, "Qos.truncate: fd"), (off_t)UNTAG(sizev)));
}
FPR_FN(fpr_g_Qos_x2etruncate, h_truncate, 2);

/* Qos.link : String -> String -> Result Unit String -- no-clobber publication */
static V h_link(V av, V bv) {
  char *a = os_cstr(av, "Qos.link: from"), *b = os_cstr(bv, "Qos.link: to");
  int r = link(a, b);
  free(a); free(b);
  return os_unit_or_errno(r);
}
FPR_FN(fpr_g_Qos_x2elink, h_link, 2);

/* Qos.syncDir : String -> Result Unit String -- make a new name durable */
static V h_sync_dir(V pathv) {
  char *path = os_cstr(pathv, "Qos.syncDir: path");
  int fd = open(path, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  free(path);
  if (fd < 0) return os_errno();
  int r = fsync(fd);
  V out = os_unit_or_errno(r);
  close(fd);
  return out;
}
FPR_FN(fpr_g_Qos_x2esyncDir, h_sync_dir, 1);

/* Qos.chmod : String -> Int -> Result Unit String */
static V h_chmod(V pathv, V modev) {
  char *path = os_cstr(pathv, "Qos.chmod: path");
  int r = chmod(path, (mode_t)UNTAG(modev));
  free(path);
  return os_unit_or_errno(r);
}
FPR_FN(fpr_g_Qos_x2echmod, h_chmod, 2);

/* Qos.machine : Unit -> String (uname -m); Qos.system : Unit -> String,
 * spelled as Python's sys.platform, which sdk.json's "os" records */
static V h_machine(V u) {
  (void)u;
  struct utsname n;
  if (uname(&n)) return os_str("", 0);
  return os_str(n.machine, (uw)strlen(n.machine));
}
FPR_FN(fpr_g_Qos_x2emachine, h_machine, 1);
static V h_system(V u) {
  (void)u;
#if defined(__APPLE__)
  return os_str("darwin", 6);
#elif defined(__FreeBSD__)
  return os_str("freebsd", 7);
#else
  return os_str("linux", 5);
#endif
}
FPR_FN(fpr_g_Qos_x2esystem, h_system, 1);

/* Qos.zeros : Int -> String -- n NUL bytes (an image's gaps) */
static V h_zeros(V nv) {
  sw n = UNTAG(nv);
  if (n < 0) fpr_cpanic("Qos.zeros: negative size");
  char *z = calloc(n ? (size_t)n : 1, 1);
  if (!z) fpr_cpanic("out of memory");
  V s = os_str(z, (uw)n);
  free(z);
  return s;
}
FPR_FN(fpr_g_Qos_x2ezeros, h_zeros, 1);

/* Qos.differences : String -> String -> List Int -- ascending offsets where
 * two equally long strings differ (mkqa --check-moved); the policy of which
 * differences are allowed stays in FP-RISC */
static V h_differences(V av, V bv) {
  const str_t *a = want_str(av, "Qos.differences: not a String"), *b = want_str(bv, "Qos.differences: not a String");
  uw n = a->len < b->len ? a->len : b->len;
  V l = (V)&os_nil;
  for (uw i = n; i-- > 0;)
    if (a->bytes[i] != b->bytes[i]) l = os_cons(TAG((sw)i), l);
  return l;
}
FPR_FN(fpr_g_Qos_x2edifferences, h_differences, 2);
