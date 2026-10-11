/* Native has no host SIGTERM or readiness file. The FP-RISC lifecycle
 * coordinator remains useful for ordinary startup-app completion. */
#include "fpr.h"
static V lifecycle_requested(V u) { (void)u; return TAG(0); }
static V lifecycle_begin(V u) { (void)u; return (V)&fpr_unit; }
static V lifecycle_complete(V status) { (void)status; return (V)&fpr_unit; }
static V lifecycle_ready(V u) { (void)u; return (V)&fpr_unit; }
FPR_FN(fpr_g_Sys_x2eshutdownRequested, lifecycle_requested, 1);
FPR_FN(fpr_g_Sys_x2eshutdownBegin, lifecycle_begin, 1);
FPR_FN(fpr_g_Sys_x2eshutdownComplete, lifecycle_complete, 1);
FPR_FN(fpr_g_Sys_x2eready, lifecycle_ready, 1);
