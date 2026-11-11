/* Whole-module native test linkage for unused Portable desktop exports. */
#include "fpr.h"
static V unavailable(void) { fpr_cpanic("nativesave: unexpected desktop operation"); return 0; }
#define UNUSED_DESKTOP(name) void name(void) { (void)unavailable(); }
UNUSED_DESKTOP(fpr_g_Sys_x2eattachImage_call6)
UNUSED_DESKTOP(fpr_g_Sys_x2ecompile_call2)
UNUSED_DESKTOP(fpr_g_glHas_call1)
UNUSED_DESKTOP(fpr_g_glInit)
UNUSED_DESKTOP(fpr_g_glMesh)
UNUSED_DESKTOP(fpr_g_glRenderUi_call3)
UNUSED_DESKTOP(fpr_g_glRender_call1)
UNUSED_DESKTOP(fpr_g_glSavePpm)
UNUSED_DESKTOP(fpr_g_inputPoll_call1)
