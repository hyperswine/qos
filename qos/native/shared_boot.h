#ifndef QOS_NATIVE_SHARED_BOOT_H
#define QOS_NATIVE_SHARED_BOOT_H
/* Native runtime ABI v4 appends the network-owner callback. The loader
 * rejects older process images before this boot structure is consumed. */
#define QOS_NET_BOOT_ABI 0x4e455431UL
typedef struct {
  fpr_sched_t *sched;
  void *reply;
  uw pid;
  void (*on_exit)(void);
  void *root;
  void *ns;
  uw net_abi;
  V (*net_owner)(void);
} qos_shared_boot_t;
#endif
