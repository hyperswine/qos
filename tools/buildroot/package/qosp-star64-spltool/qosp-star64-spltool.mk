# Vendor boot ROM header tool, retained from Buildroot 2025.02's board port.
QOSP_STAR64_SPLTOOL_VERSION = JH7110_VF2_515_v5.11.3
QOSP_STAR64_SPLTOOL_SITE = $(call github,starfive-tech,soft_3rdpart,$(QOSP_STAR64_SPLTOOL_VERSION))
QOSP_STAR64_SPLTOOL_LICENSE = GPL-2.0+
QOSP_STAR64_SPLTOOL_LICENSE_FILES = spl_tool/LICENSE

define HOST_QOSP_STAR64_SPLTOOL_BUILD_CMDS
	$(HOST_MAKE_ENV) $(MAKE) $(HOST_CONFIGURE_OPTS) -C $(@D)/spl_tool
endef

define HOST_QOSP_STAR64_SPLTOOL_INSTALL_CMDS
	$(INSTALL) -D -m 0755 $(@D)/spl_tool/spl_tool $(HOST_DIR)/bin/spl_tool
endef

$(eval $(host-generic-package))
