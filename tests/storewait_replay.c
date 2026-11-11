/* Only the measured Qlog actor writes these per-replay totals. The test
 * kernel reads them after the loaded client's final reply. All times are
 * guest wall-clock ticks and include time descheduled inside a span. */
#include "fpr.h"

enum { RECORDS, READ_TICKS, CONCAT_TICKS, REPLAY_TICKS, PAGES, PAGE_TICKS, PAYLOAD_TICKS, SLICE_TICKS, BLOCK_READS, LOCK_TICKS, TRANSFER_TICKS, COPY_TICKS, TIMELINE, EMPTY_POLLS = TIMELINE + 6, PARKED, PRE_PUBLISH, MAILBOX, POST_RECEIVE, DISTINCT, FIELDS };
static uw replay_samples[128][FIELDS];
static unsigned completed;

/* One client, one outstanding pageRead. Qlog arms the page number and
 * its separate block I/O worker consumes it before returning the reply. */
static uw expected_page;

/* Request ID follows the block owner, its worker, and its relay. One
 * request in flight; their mailbox operations synchronize the stages. */
static V trace_id;
static uint64_t stamp[6];
static uint64_t last_stamp[128][7];

#ifdef QOS_POLL_TRIAL
static uw relay_key;
static uint64_t published, dequeued;
static uw seen[128];
unsigned qos_trial_poll_us = 200;
void qos_trial_polls(uw page, uw count, uint64_t ticks) {
    if (__atomic_load_n(&expected_page, __ATOMIC_ACQUIRE) != page + 1) return;
    replay_samples[completed][EMPTY_POLLS] += count;
    replay_samples[completed][PARKED] += ticks;
}
/* Immediately before the runtime release-publishes the correlated tuple. */
void qos_trial_publish(uw key, V m) {
    if (!key || key != __atomic_load_n(&relay_key, __ATOMIC_ACQUIRE)) return;
    if (!ISINT(m) && TID(m) == T_TUP3 && FPR_FLD(m,1) == trace_id)
        published = hal_mtime();
}
static V owner_received(V m) {
    uw key = __atomic_load_n(&relay_key, __ATOMIC_ACQUIRE);
    if (key && !ISINT(m) && TID(m) == T_TUP3 &&
        (uw)FPR_FLD(m,0) == key && FPR_FLD(m,1) == trace_id)
        dequeued = hal_mtime();
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2eownerReceived, owner_received, 1);
static V reuse_page;
static V trial_interval(V us, V reuse) {
    uw n = UNTAG(us);
    if (n != 50 && n != 100 && n != 200) fpr_cpanic("invalid trial interval");
    reuse_page = reuse;
    qos_trial_poll_us = n;
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2etrialInterval, trial_interval, 2);
static V trial_reuse(V ignored) { (void)ignored; return reuse_page; }
FPR_FN(fpr_g_Sys_x2etrialReuse, trial_reuse, 1);
static uw beats;
static V heartbeat(V ignored) {
    (void)ignored;
    return TAG(__atomic_add_fetch(&beats,1,__ATOMIC_RELAXED));
}
FPR_FN(fpr_g_Sys_x2eheartbeat, heartbeat, 1);
static V beat_count(V ignored) {
    (void)ignored;
    return TAG(__atomic_load_n(&beats,__ATOMIC_RELAXED));
}
FPR_FN(fpr_g_Sys_x2ebeatCount, beat_count, 1);
#endif

static V mark_stage(V stage, V id) {
    uw n = UNTAG(stage);
    if (!n && __atomic_load_n(&expected_page, __ATOMIC_ACQUIRE)) {
        if (trace_id) fpr_cpanic("overlapping block request");
        trace_id = id;
    }
    if (!trace_id) return (V)&fpr_unit;
    if (id != trace_id || n >= 6 || stamp[n])
        fpr_cpanic("uncorrelated block timeline");
    stamp[n] = hal_mtime();
#ifdef QOS_POLL_TRIAL
    if (n == 4) __atomic_store_n(&relay_key,(uw)fpr_hart()->current,__ATOMIC_RELEASE);
    if (n == 5) {
        if (!(stamp[4] <= published && published <= dequeued && dequeued <= stamp[5]))
            fpr_cpanic("invalid relay publication timeline");
        replay_samples[completed][PRE_PUBLISH] += published - stamp[4];
        replay_samples[completed][MAILBOX] += dequeued - published;
        replay_samples[completed][POST_RECEIVE] += stamp[5] - dequeued;
        __atomic_store_n(&relay_key,0,__ATOMIC_RELEASE);
        published = dequeued = 0;
    }
#endif
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2eblockStage, mark_stage, 2);

void qos_replay_device_stamps(uw page, uint64_t submitted, uint64_t observed) {
    if (__atomic_load_n(&expected_page, __ATOMIC_ACQUIRE) != page + 1) return;
    if (!trace_id || stamp[1]) fpr_cpanic("unexpected virtio submission");
    stamp[1] = submitted;
    stamp[2] = observed;
}

static V finish_timeline(V end) {
    uint64_t next = UNTAG(end);
    last_stamp[completed][6] = next;
    for (int i = 5; i >= 0; --i) {
        if (!stamp[i] || stamp[i] > next) fpr_cpanic("invalid block timeline");
        replay_samples[completed][TIMELINE + i] += next - stamp[i];
        next = last_stamp[completed][i] = stamp[i];
        stamp[i] = 0;
    }
    trace_id = 0;
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2eblockTimelineEnd, finish_timeline, 1);

static V last_block_stamp(V row, V field) {
    uw r = UNTAG(row), f = UNTAG(field);
    if (r >= completed || f >= 7) fpr_cpanic("invalid block stamp index");
    return TAG(last_stamp[r][f]);
}
FPR_FN(fpr_g_Sys_x2elastBlockStamp, last_block_stamp, 2);

static V page_begin(V page) {
#ifdef QOS_POLL_TRIAL
    uw n = replay_samples[completed][DISTINCT];
    uw i = 0;
    while (i < n && seen[i] != (uw)UNTAG(page)) ++i;
    if (i == n) {
        if (n >= 128) fpr_cpanic("unexpected page count");
        seen[n] = UNTAG(page);
        replay_samples[completed][DISTINCT]++;
    }
#endif
    if (__atomic_exchange_n(&expected_page, (uw)UNTAG(page) + 1, __ATOMIC_ACQ_REL))
        fpr_cpanic("overlapping replay pages");
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2ereplayPageBegin, page_begin, 1);

void qos_replay_blk_cost(uw page, uint64_t lock, uint64_t transfer, uint64_t copy) {
    uw expected = page + 1;
    if (!__atomic_compare_exchange_n(&expected_page, &expected, 0, 0,
                                     __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) return;
    if (completed >= 128) fpr_cpanic("unexpected replay block read");
    uw *row = replay_samples[completed];
    row[BLOCK_READS]++;
    row[LOCK_TICKS] += lock;
    row[TRANSFER_TICKS] += transfer;
    row[COPY_TICKS] += copy;
}

static V page_cost(V ticks) {
    if (__atomic_load_n(&expected_page, __ATOMIC_ACQUIRE)) fpr_cpanic("missing replay block read");
    if (completed >= 128) fpr_cpanic("unexpected replay page");
    replay_samples[completed][PAGES]++;
    replay_samples[completed][PAGE_TICKS] += UNTAG(ticks);
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2ereplayPageCost, page_cost, 1);

static V payload_cost(V payload, V slice) {
    if (completed >= 128) fpr_cpanic("unexpected replay payload");
    replay_samples[completed][PAYLOAD_TICKS] += UNTAG(payload);
    replay_samples[completed][SLICE_TICKS] += UNTAG(slice);
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2ereplayPayloadCost, payload_cost, 2);

static V record_cost(V read_ticks, V concat_ticks) {
    if (completed >= 128) fpr_cpanic("unexpected replay");
    uw *row = replay_samples[completed];
    row[RECORDS]++;
    row[READ_TICKS] += UNTAG(read_ticks);
    row[CONCAT_TICKS] += UNTAG(concat_ticks);
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2ereplayRecordCost, record_cost, 2);

static V replay_done(V ticks) {
    if (completed >= 128) fpr_cpanic("unexpected replay completion");
    replay_samples[completed++][REPLAY_TICKS] = UNTAG(ticks);
    return (V)&fpr_unit;
}
FPR_FN(fpr_g_Sys_x2ereplayDone, replay_done, 1);

static V replay_metric(V row, V field) {
    uw i = UNTAG(row), j = UNTAG(field);
    if (i >= completed || j >= FIELDS) fpr_cpanic("missing replay sample");
    return TAG(replay_samples[i][j]);
}
FPR_FN(fpr_g_Sys_x2ereplayMetric, replay_metric, 2);
