# ---- QOSPortable profile: the app side ---------------------------------
# App and plugin pipelines now live in tools/build-checkout-app.sol.
# These targets forward to it so existing `make qos-app` / `make plugin-qa`
# invocations continue working without duplicating the 3-arch build rules.

PLUGID    = $(basename $(notdir $(SOURCE)))
PLUG_OUT ?= $(PLUGID).qa
QOS_APP_ID = $(if $(QA_ID),$(QA_ID),$(basename $(notdir $(SOURCE))))
QOS_APP_NAME = $(if $(QA_NAME),$(QA_NAME),$(QOS_APP_ID))
QOS_APP_VERSION = $(if $(QA_VERSION),$(QA_VERSION),1)
qos_shell_arg = '$(subst ','"'"',$(1))'
QOS_APP_ASSIGN = $(call qos_shell_arg,QA_ID=$(QOS_APP_ID)) $(call qos_shell_arg,QA_NAME=$(QOS_APP_NAME)) $(call qos_shell_arg,QA_VERSION=$(QOS_APP_VERSION))

ifneq ($(filter arm64 aarch64,$(shell uname -m)),)
APP_HOST ?= a64
else ifneq ($(filter riscv64,$(shell uname -m)),)
APP_HOST ?= rv64
else
APP_HOST ?= x64
endif

qos-app-x64 qos-app-a64 qos-app-rv64: fprc
	APP_HOST=$(subst qos-app-,,$@) QOSHARTS=$(QOSHARTS) QOSSLAB=$(QOSSLAB) QOSSTACK=$(QOSSTACK) QOSCFLAGS_EXTRA="$(QOSCFLAGS_EXTRA)" \
	  "$(FPRC)" sol tools/build-checkout-app.sol app "$(SOURCE)" "$(QA_OUT)" "$(BUILD)" "$(HARTS)" $(QOS_APP_ASSIGN)

plugin-qa-x64 plugin-qa-a64 plugin-qa-rv64: fprc
	APP_HOST=$(subst plugin-qa-,,$@) QOSCFLAGS_EXTRA="$(QOSCFLAGS_EXTRA)" \
	  "$(FPRC)" sol tools/build-checkout-app.sol plugin "$(SOURCE)" "$(PLUG_OUT)" "$(BUILD)"

qos-app: qos-app-$(APP_HOST)
plugin-qa: plugin-qa-$(APP_HOST)

qos-app-a64-run: qos-app-a64
	$(MAKE) -C $(QOS) portable
	$(QOS)/qosp --yes $(QA_OUT)

qos-app-mac-object: fprc $(SOURCE) $(FPRISC_ROOT)/core/prelude.fpr
	@mkdir -p $(BUILD)
	LC_ALL=C.UTF-8 "$(FPRC)" --target=qa64mac --prelude=$(FPRISC_ROOT)/core/prelude.fpr $(SOURCE) $(BUILD)/qosapp-mac.s
	clang --target=arm64-apple-macos11 -c $(BUILD)/qosapp-mac.s -o $(BUILD)/qosapp-mac.o
	@echo "emitted $(BUILD)/qosapp-mac.s (Mach-O syntax, QOS-app cells)"

.PHONY: qos-app plugin-qa qos-app-x64 plugin-qa-x64 qos-app-a64 plugin-qa-a64 qos-app-rv64 plugin-qa-rv64 qos-app-a64-run qos-app-mac-object
