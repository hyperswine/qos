/* Single-client native benchmark. Sender writes sent before the mailbox
 * release-publishes the reply; receiver reads it after acquiring the reply.
 * The request send similarly publishes the expected endpoints and ID. */
#include "fpr.h"

static struct {
    V caller, owner, id;
    uint64_t sent;
} pending;

static struct {
    uint64_t sent, received;
} samples[256];
static unsigned count;

void qos_trace_request(V caller, V owner, V id) {
    if (pending.caller) fpr_cpanic("store trace: overlapping requests");
    pending.caller = caller;
    __atomic_store_n(&pending.owner, owner, __ATOMIC_RELEASE);
    pending.id = id;
    pending.sent = 0;
}

void qos_trace_publish(uw sender, V target, V message) {
    /* Only the storage actor accesses pending on the publication path. */
    if ((V)sender != __atomic_load_n(&pending.owner, __ATOMIC_ACQUIRE)) return;
    if (target != pending.caller || ISINT(message) || TID(message) != T_TUP2 ||
        FPR_FLD(message, 0) != pending.id) return;
    if (pending.sent) fpr_cpanic("store trace: duplicate reply");
    pending.sent = hal_mtime();
}

void qos_trace_received(V owner, V caller, V id, uint64_t received) {
    if (owner != pending.owner || caller != pending.caller || id != pending.id ||
        !pending.sent || received < pending.sent || count >= 256)
        fpr_cpanic("store trace: missing or invalid reply timestamp");
    samples[count].sent = pending.sent;
    samples[count++].received = received;
    pending.caller = 0;
}

static V trace_stamp(V index) {
    uw i = (uw)UNTAG(index);
    if (i / 2 >= count) fpr_cpanic("store trace: missing sample");
    return TAG(i % 2 ? samples[i / 2].received : samples[i / 2].sent);
}
FPR_FN(fpr_g_Sys_x2estoreTraceStamp, trace_stamp, 1);
