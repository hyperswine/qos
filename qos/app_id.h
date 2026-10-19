/* app_id.h -- what an app id may be, checked in C where an id becomes a
 * path or a url: the portable host (qos/portable/host.c, store.c binds
 * qos-store/<id>.kv) and the native kernel (loader/process.c places the
 * process and builds apps/<id>/<id>.kv).  The launchers refuse a bad id
 * first, by name, when they parse the manifest (programs/mods/manifest.fpr
 * validId); these are the same rule again, below the parser.
 *
 * An id is ONE safe path component: 1..64 bytes of A-Z a-z 0-9 _ - .,
 * not starting with '.' or '-', with no "..".  So "../escaped", "a/b",
 * ".", ".." and over-long ids (which the native url used to truncate,
 * letting two ids that share a prefix share a store) are refused. */
#ifndef QOS_APP_ID_H
#define QOS_APP_ID_H

#define QOS_APP_ID_MAX 64u

/* NULL when the id is valid, else the reason */
static inline const char *qos_app_id_invalid(const unsigned char *id, unsigned long n) {
  if (!id || n == 0) return "app id: missing";
  if (n > QOS_APP_ID_MAX) return "app id: longer than 64 bytes";
  if (id[0] == '.' || id[0] == '-') return "app id: may not start with '.' or '-'";
  for (unsigned long i = 0; i < n; i++) {
    unsigned char c = id[i];
    int ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
             c == '_' || c == '-' || c == '.';
    if (!ok) return "app id: may use only A-Z a-z 0-9 _ - .";
    if (c == '.' && i + 1 < n && id[i + 1] == '.') return "app id: may not contain \"..\"";
  }
  return 0;
}
#endif
