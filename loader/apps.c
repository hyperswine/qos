/* apps.c -- the baked-in .qa app registry (the rodata half of /apps).
 *
 * QOS apps live at /apps/<Id>.qa. This file is the SHIPPED set: .qa
 * archives compiled into the image as rodata. A disk-backed /apps
 * overrides these by Id at the System.qa layer -- rodata is the
 * fallback, disk is the install target (docs/2026-07-19-QA-FORMAT.md).
 * Every app runs as a loaded process (Sys.placeImageAt, loader/process.c);
 * the co-compiled name->entry table and Apps.entry/Apps.run are gone.
 *
 * The table, generated into apps_data.c by tools/genapps.py:
 *   fpr_qa_blobs[]   : { id, bytes, len }   the .qa archives
 *
 * FPRISC surface (fpr_g_*):
 *   Apps.list  Unit   -> String   newline-joined app ids present in rodata
 *   Apps.read  id     -> String   the raw .qa bytes for that id (Err-empty
 *                                  if absent; the VFS turns "" into Err)
 */
#include "fpr.h"

typedef struct { const char *id; const unsigned char *bytes; uw len; } qa_blob_t;
typedef struct { const char *symbol; const pap0_t *pap; } app_entry_t;

extern const qa_blob_t fpr_qa_blobs[];   /* apps_data.c, zero-terminated */

static int streq_cs(const char *c, const str_t *s) {
  uw n = 0; while (c[n]) n++;
  if (n != s->len) return 0;
  for (uw i = 0; i < n; i++) if ((unsigned char)c[i] != s->bytes[i]) return 0;
  return 1;
}

static V g_apps_list(V unit) {
  (void)unit;
  /* build "id1\nid2\n..." with strcat via the render buffer would need
   * a String builder; instead concatenate through fpr_mkstr + strcat */
  V acc = (V)fpr_mkstr((const uint8_t *)"", 0);
  extern V fpr_prim_fn_strcat(V, V);
  for (const qa_blob_t *b = fpr_qa_blobs; b->id; b++) {
    uw n = 0; while (b->id[n]) n++;
    V line = (V)fpr_mkstr((const uint8_t *)b->id, n);
    acc = fpr_prim_fn_strcat(acc, line);
    acc = fpr_prim_fn_strcat(acc, (V)fpr_mkstr((const uint8_t *)"\n", 1));
  }
  return acc;
}

static V g_apps_read(V id) {
  if (ISINT(id) || TID(id) != T_STR) fpr_cpanic("Apps.read: id not a String");
  const str_t *s = (const str_t *)id;
  for (const qa_blob_t *b = fpr_qa_blobs; b->id; b++)
    if (streq_cs(b->id, s))
      return (V)fpr_mkstr(b->bytes, b->len);
  return (V)fpr_mkstr((const uint8_t *)"", 0); /* absent: empty */
}

/* Apps.entry / Apps.run: DELETED with name-dispatch.  The launcher is
 * System.qa's builtin shell; every other app is a loaded process. */

FPR_FN(fpr_g_Apps_x2elist, g_apps_list, 1);
FPR_FN(fpr_g_Apps_x2eread, g_apps_read, 1);
