/* Only the measured Qlog actor writes these per-replay totals. The test
 * kernel reads them after the loaded client's final reply. All times are
 * guest wall-clock ticks and include time descheduled inside a span. */
#include "fpr.h"

enum { RECORDS, READ_TICKS, CONCAT_TICKS, REPLAY_TICKS, PAGES, PAGE_TICKS, PAYLOAD_TICKS, SLICE_TICKS, BLOCK_READS, LOCK_TICKS, TRANSFER_TICKS, COPY_TICKS, FIELDS };
static uw replay_samples[128][FIELDS];
static unsigned completed;

/* One client, one outstanding pageRead. Qlog arms the page number and
 * its separate block I/O worker consumes it before returning the reply. */
static uw expected_page;

static V page_begin(V page) {
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
