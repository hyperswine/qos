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
#   FPRBUILD_EXTRA=--target=linux-<arch> --cc <target gcc>
#                                     select ISA and link for the target
#   QOSP_ARCH=<target arch>            decide -ffixed-x28 by the TARGET
#   QOSP_ES_OUT=<path>                 write the binary into Buildroot's tree
#
# `fpr` itself is a Haskell program and stays out of Buildroot: it runs on
# the build machine, from the fprisc checkout, and only ever emits assembly
# for the selected target, independently of the build machine's ISA.
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

# Select the target ISA and runtime, including on a different build host.
QOSP_TARGET_ARCH = $(call qstrip,$(BR2_ARCH))

define QOSP_CHECK_TREE
	case "$(QOSP_TARGET_ARCH)" in aarch64|x86_64|riscv64) ;; \
		*) echo "qosp: unsupported Linux architecture $(QOSP_TARGET_ARCH)"; exit 1 ;; esac
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
	$(TARGET_CC) $(TARGET_CFLAGS) -O2 -Wall -Wextra \
		$(QOSP_PKGDIR)/qosp-service-guard.c -o $(@D)/qosp-service-guard $(TARGET_LDFLAGS)
	$(if $(filter y,$(BR2_PACKAGE_QOSP_BOOT_SPLASH)),\
		$(TARGET_CC) $(TARGET_CFLAGS) -O2 -Wall -Wextra \
		-I$(QOSP_QOS_DIR)/hal/unix $(QOSP_PKGDIR)/qosp-splash.c \
		-o $(@D)/qosp-splash $(TARGET_LDFLAGS) -lm)
	$(MAKE1) -C $(QOSP_QOS_DIR)/qos portable-es \
		FPRISC_ROOT="$(QOSP_FPRISC_DIR)" \
		QOSP_ARCH="$(QOSP_TARGET_ARCH)" \
		QOSP_ES_OUT="$(@D)/qosp" \
		FPRBUILD_EXTRA="--target=linux-$(QOSP_TARGET_ARCH) --cc $(TARGET_CC)" \
		SND_FLAGS="$(QOSP_SND_FLAGS)" \
		SND_LIBS="$(QOSP_SND_LIBS)"
endef

define QOSP_INSTALL_TARGET_CMDS
	# Bake the state directory into the persistent rootfs, before first boot.
	# fsync(disk + immediate parent) cannot persist a newly created ancestor,
	# and following a custom skeleton's /var link could put state in tmpfs.
	for path in $(TARGET_DIR)/var $(TARGET_DIR)/var/lib $(TARGET_DIR)/var/lib/qosp; do \
		test ! -L "$$path" || { \
			echo "qosp: default state path must use real directories: $$path" >&2; exit 1; }; \
	done
	$(INSTALL) -d -m 0755 $(TARGET_DIR)/var/lib/qosp
	$(INSTALL) -D -m 0755 $(@D)/qosp $(TARGET_DIR)/usr/bin/qosp
	$(INSTALL) -D -m 0755 $(@D)/qosp-service-guard $(TARGET_DIR)/usr/bin/qosp-service-guard
	$(INSTALL) -D -m 0644 $(QOSP_APP) $(TARGET_DIR)/usr/share/qosp/app.qa
	$(INSTALL) -D -m 0755 $(QOSP_PKGDIR)/qosp-session \
		$(TARGET_DIR)/usr/bin/qosp-session
	$(INSTALL) -D -m 0755 $(QOSP_PKGDIR)/qosp-supervise \
		$(TARGET_DIR)/usr/bin/qosp-supervise
	$(INSTALL) -D -m 0644 $(QOSP_PKGDIR)/qosp-service.sh \
		$(TARGET_DIR)/usr/lib/qosp-service.sh
	$(if $(filter y,$(BR2_PACKAGE_QOSP_MAIN_PROFILE)),\
		$(INSTALL) -D -m 0644 $(QOSP_MAIN_DIR)/Main.disk $(TARGET_DIR)/usr/share/qosp/Main.disk)
	$(if $(filter y,$(BR2_PACKAGE_QOSP_BOOT_SPLASH)),\
		$(INSTALL) -D -m 0755 $(@D)/qosp-splash $(TARGET_DIR)/usr/bin/qosp-splash)
	$(if $(filter y,$(BR2_PACKAGE_QOSP_BOOT_SPLASH)),\
		$(INSTALL) -D -m 0644 $(QOSP_QOS_DIR)/assets/qos-boot-logo.svg \
		$(TARGET_DIR)/usr/share/qosp/boot-logo.svg)
endef

ifeq ($(BR2_PACKAGE_QOSP_AUTOSTART),y)
define QOSP_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(QOSP_PKGDIR)/S99qosp $(TARGET_DIR)/etc/init.d/S99qosp
	# Remove the previous pre-coldplug name in incremental image builds.
	rm -f $(TARGET_DIR)/etc/init.d/S02qosp-splash
	$(if $(filter y,$(BR2_PACKAGE_QOSP_BOOT_SPLASH)),\
		$(INSTALL) -D -m 0755 $(QOSP_PKGDIR)/S12qosp-splash $(TARGET_DIR)/etc/init.d/S12qosp-splash)
endef
endif

ifeq ($(BR2_PACKAGE_QOSP_BOOT_SPLASH),y)
define QOSP_INSTALL_SPLASH_DEFAULTS
	$(INSTALL) -d -m 0755 $(TARGET_DIR)/etc/default
	touch $(TARGET_DIR)/etc/default/qosp
	sed -i '/# QOSP_BOOT_SPLASH$$/d' $(TARGET_DIR)/etc/default/qosp
	printf 'export FPR_BOOT_SPLASH=1 # QOSP_BOOT_SPLASH\n' >> $(TARGET_DIR)/etc/default/qosp
endef
QOSP_POST_INSTALL_TARGET_HOOKS += QOSP_INSTALL_SPLASH_DEFAULTS
endif

$(eval $(generic-package))
