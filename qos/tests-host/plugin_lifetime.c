#include "../appside/qos_abi.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int64_t qosp_load_plugin(const qos_plugin_t *, char *, uint64_t);
int64_t qosp_unload_plugin(const qos_unload_t *, char *, uint64_t);

/* Called under store_mu before the caller can execute the published plugin. */
void qosp_check_plugin_lifetime(const qos_plugin_t *plugin, int64_t entry) {
  char err[256] = "";
  qos_unload_t range = {plugin->base, plugin->execsz + 1};
  if (qosp_unload_plugin(&range, err, sizeof err) >= 0 ||
      !strstr(err, "not a published plugin range")) goto failed;
  if (qosp_load_plugin(plugin, err, sizeof err) >= 0 ||
      !strstr(err, "overlaps a published image")) goto failed;
  range.execsz = plugin->execsz;
  if (qosp_unload_plugin(&range, err, sizeof err) < 0) goto failed;
  if (qosp_unload_plugin(&range, err, sizeof err) >= 0 ||
      !strstr(err, "not a published plugin range")) goto failed;
  qos_plugin_t changed = *plugin;
  changed.sha = plugin->relsha;
  if (qosp_load_plugin(&changed, err, sizeof err) >= 0 ||
      !strstr(err, "IMAGE sha256 mismatch")) goto failed;
  changed = *plugin;
  changed.relsha = plugin->sha;
  if (qosp_load_plugin(&changed, err, sizeof err) >= 0 ||
      !strstr(err, "RELOC sha256 mismatch")) goto failed;
  if (qosp_load_plugin(plugin, err, sizeof err) != entry) goto failed;
  fprintf(stderr, "plugin publication lifecycle passed\n");
  return;
failed:
  fprintf(stderr, "plugin publication lifecycle failed: %s\n", err);
  abort();
}
