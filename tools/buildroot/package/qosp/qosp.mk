################################################################################
#
# qosp -- QOS Portable, built from a working tree with Buildroot's toolchain
#
# There is nothing to download.  qosp is an FP-RISC program (qos/portable/
# qosp.fpr) whose HAL is the C under qos/hal/unix, and the thing that knows
# how to put those together is the qos tree's own Makefile.  So this package
# CALLS that Makefile rather than restating its source list -- `portable-es`,
# the EGL/GLES target, through three hooks it exposes for exactly this:
#
#   FPRBUILD_EXTRA=--cc <target gcc>   compile and link for the target
#   QOSP_ARCH=<target arch>            decide -ffixed-x28 by the TARGET
#   QOSP_ES_OUT=<path>                 write the binary into Buildroot's tree
#
# `fpr` itself is a Haskell program and stays out of Buildroot: it runs on
# the build machine, from the fprisc checkout, and only ever emits assembly
# for the target -- which for an aarch64 build machine and an aarch64 target
# is the same assembly the host build makes.
#
################################################################################

QOSP_VERSION = local
QOSP_SOURCE =
# no QOSP_LICENSE: the qos tree states no license, and this is not the
# place to invent one.  `make legal-info` will say so rather than lie.
QOSP_DEPENDENCIES = libegl libgles

QOSP_QOS_DIR = $(call qstrip,$(BR2_PACKAGE_QOSP_QOS_DIR))
QOSP_FPRISC_DIR = $(or $(call qstrip,$(BR2_PACKAGE_QOSP_FPRISC_DIR)),\
	$(QOSP_QOS_DIR)/../fprisc)
QOSP_APP = $(or $(call qstrip,$(BR2_PACKAGE_QOSP_APP)),$(QOSP_QOS_DIR)/app.qa)
ifeq ($(BR2_PACKAGE_QOSP_MAIN_PROFILE),y)
QOSP_MAIN_DIR = $(call qstrip,$(BR2_PACKAGE_QOSP_MAIN_DIR))
QOSP_APP = $(QOSP_MAIN_DIR)/main.qa
endif

# the sound tier is ALSA when the image has it, and the WAV dump otherwise:
# the same rule the host build applies, decided here because a cross build
# must not ask the build machine's pkg-config
ifeq ($(BR2_PACKAGE_ALSA_LIB),y)
QOSP_DEPENDENCIES += alsa-lib
QOSP_SND_FLAGS = -DQOSP_SND_ALSA
QOSP_SND_LIBS = -lasound
endif

define QOSP_EXTRACT_CMDS
	mkdir -p $(@D)
endef

# `fpr build --cc` crosses to another LIBC, not to another ARCH: Build.hs
# still reads the BUILD machine for the context switch, -ffixed-x28 and
# -no-pie (fprisc/docs/BOUNDS.md).  Refuse loudly rather than emit a binary
# that is wrong in three places and says nothing.
QOSP_TARGET_ARCH = $(call qstrip,$(BR2_ARCH))

define QOSP_CHECK_TREE
	test "$$(uname -m)" = "$(QOSP_TARGET_ARCH)" || { \
		echo "qosp: this builds $(QOSP_TARGET_ARCH), on a $$(uname -m) machine."; \
		echo "qosp: fpr's --cc crosses libc, not architecture -- build on a"; \
		echo "qosp: $(QOSP_TARGET_ARCH) host (tools/arm64-vm) or fix Build.hs."; \
		exit 1; }
	test -x $(QOSP_FPRISC_DIR)/fpr || { \
		echo "qosp: no built compiler at $(QOSP_FPRISC_DIR)/fpr"; \
		echo "qosp: build it first (make fpr in the fprisc checkout),"; \
		echo "qosp: or set BR2_PACKAGE_QOSP_FPRISC_DIR"; exit 1; }
	test -f $(QOSP_APP) || { \
		echo "qosp: no application image at $(QOSP_APP)"; \
		echo "qosp: make qos-app PROG=programs/<prog>.fpr, or set"; \
		echo "qosp: BR2_PACKAGE_QOSP_APP"; exit 1; }
endef

define QOSP_BUILD_CMDS
	$(QOSP_CHECK_TREE)
	$(MAKE1) -C $(QOSP_QOS_DIR)/qos portable-es \
		FPRISC_ROOT="$(QOSP_FPRISC_DIR)" \
		QOSP_ARCH="$(QOSP_TARGET_ARCH)" \
		QOSP_ES_OUT="$(@D)/qosp" \
		FPRBUILD_EXTRA="--cc $(TARGET_CC)" \
		SND_FLAGS="$(QOSP_SND_FLAGS)" \
		SND_LIBS="$(QOSP_SND_LIBS)"
endef

define QOSP_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/qosp $(TARGET_DIR)/usr/bin/qosp
	$(INSTALL) -D -m 0644 $(QOSP_APP) $(TARGET_DIR)/usr/share/qosp/app.qa
	$(INSTALL) -D -m 0755 $(QOSP_PKGDIR)/qosp-session \
		$(TARGET_DIR)/usr/bin/qosp-session
	$(if $(filter y,$(BR2_PACKAGE_QOSP_MAIN_PROFILE)),\
		$(INSTALL) -D -m 0644 $(QOSP_MAIN_DIR)/Main.disk $(TARGET_DIR)/usr/share/qosp/Main.disk)
endef

ifeq ($(BR2_PACKAGE_QOSP_AUTOSTART),y)
define QOSP_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(QOSP_PKGDIR)/S99qosp $(TARGET_DIR)/etc/init.d/S99qosp
endef
endif

$(eval $(generic-package))
