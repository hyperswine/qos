QOSP_STAR64_TOOLS_VERSION = local
QOSP_STAR64_TOOLS_SOURCE =
QOSP_STAR64_TOOLS_DEPENDENCIES = libegl libgles
QOSP_STAR64_TOOLS_LICENSE = MIT

define QOSP_STAR64_TOOLS_EXTRACT_CMDS
	mkdir -p $(@D)
endef

define QOSP_STAR64_TOOLS_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra \
		$(QOSP_STAR64_TOOLS_PKGDIR)/egl-check.c -o $(@D)/star64-egl-check \
		$(TARGET_LDFLAGS) -lEGL -lGLESv2
endef

define QOSP_STAR64_TOOLS_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/star64-egl-check $(TARGET_DIR)/usr/bin/star64-egl-check
endef

$(eval $(generic-package))
