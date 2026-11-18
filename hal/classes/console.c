/* console.c -- the CONSOLE class's FP-RISC primitives, once for every driver.
 *
 * Each finds the instance behind its Device (devtable_entry_of), checks the
 * arguments against console.h and calls the instance's ops. A wrong argument
 * TYPE is a programming error (fpr_cpanic). */
#include "fpr.h"
#include "devtable.h"
#include "console.h"

#define CON_READ_MAX 512u /* bytes one conRead hands over */

static const qos_console_ops *instance(V d, void **st) {
  if (ISINT(d) || !d || TID(d) != T_DEVICE) fpr_cpanic("con: not a Device");
  const devtable_entry_t *e = devtable_entry_of(d);
  if (e->cls != FPR_DEV_CONSOLE || !e->ops) fpr_cpanic("con: not a console device");
  const qos_console_ops *ops = (const qos_console_ops *)e->ops;
  if (ops->version != QOS_CONSOLE_OPS_VERSION) fpr_cpanic("con: driver built for another console contract");
  *st = e->state;
  return ops;
}

static V h_conOpen(V d) {
  void *st;
  instance(d, &st)->open(st);
  return TAG(0);
}

static V h_conWrite(V d, V sv) {
  void *st;
  const qos_console_ops *ops = instance(d, &st);
  if (ISINT(sv) || !sv || TID(sv) != T_STR) fpr_cpanic("conWrite: bytes must be a String");
  str_t *s = (str_t *)sv;
  return TAG((sw)ops->write(st, (const uint8_t *)s->bytes, (uint32_t)s->len));
}

static V h_conRead(V d) {
  void *st;
  const qos_console_ops *ops = instance(d, &st);
  uint8_t buf[CON_READ_MAX];
  uint32_t n = ops->read(st, buf, CON_READ_MAX);
  str_t *s = (str_t *)fpr_alloc(sizeof(str_t) + n);
  s->tid = T_STR; s->var = 0; s->len = n;
  for (uint32_t i = 0; i < n; i++) s->bytes[i] = (char)buf[i];
  return (V)s;
}

static V h_conArm(V d, V rx, V tx) {
  void *st;
  const qos_console_ops *ops = instance(d, &st);
  if (!ISINT(rx) || !ISINT(tx)) fpr_cpanic("conArm: rx and tx must be Ints");
  ops->arm(st, UNTAG(rx) != 0, UNTAG(tx) != 0);
  return TAG(0);
}

static V h_conSize(V d) {
  void *st;
  const qos_console_ops *ops = instance(d, &st);
  return TAG((sw)(ops->size ? ops->size(st) : 0));
}

FPR_FN(fpr_g_conOpen, h_conOpen, 1);
FPR_FN(fpr_g_conWrite, h_conWrite, 2);
FPR_FN(fpr_g_conRead, h_conRead, 1);
FPR_FN(fpr_g_conArm, h_conArm, 3);
FPR_FN(fpr_g_conSize, h_conSize, 1);
