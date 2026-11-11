/* Only the measured Qlog actor writes these per-replay totals. The test
 * kernel reads them after the loaded client's final reply. All times are
 * guest wall-clock ticks and include time descheduled inside a span. */
#include "fpr.h"

enum { RECORDS, READ_TICKS, CONCAT_TICKS, REPLAY_TICKS, FIELDS };
static uw replay_samples[128][FIELDS];
static unsigned completed;

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
