#ifndef QOS_NATIVE_SHARED_BOOT_H
#define QOS_NATIVE_SHARED_BOOT_H
/* The shared-plane boot block: the kernel fills it, the process's entry
 * reads it.  Its layout is part of FPR_NATIVE_ABI (v5 carries the two
 * plane tables apart; v4 appended the network-owner callback).  The
 * loader rejects images built against another FPR_NATIVE_ABI before this
 * block is consumed; the entry then checks each table's own version and
 * REFUSES (writes `refused`, spawns nothing) on a table it was not built
 * against, so the two contracts can move without moving the layout. */
#define QOS_NET_BOOT_ABI 0x4e455431UL
typedef struct {
  fpr_plane_actors_t *actors;  /* the scheduler contract (fpr.h) */
  fpr_plane_memory_t *memory;  /* the shared-heap contract (fpr.h) */
  void *reply;
  uw pid;
  void (*on_exit)(void);
  void *root;
  void *ns;
  uw net_abi;
  V (*net_owner)(void);
  const char *refused;         /* set by the entry: why it did not start */
} qos_shared_boot_t;
#endif
