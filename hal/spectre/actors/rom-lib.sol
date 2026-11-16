# Uploads through the boot ROM for the actor probes: one run of spectre-uart
# (hal/spectre/tools/spectre-uart.c) per conversation, so nothing the probe
# says between two steps is lost. SPECTRE_UART_TOOL names the built helper.
unsafe program.
B = use "sol/lib/build".
tool = B.setting "SPECTRE_UART_TOOL" "spectre-uart".
uart port ops = case Proc.runNow (ProcessSpec (tool :: port :: ops) "" [] "" 0) of
    Ok (ProcessResult 0 out _) -> out
  | Ok (ProcessResult code out err) -> error "spectre-uart exited {code}: {err}{out}"
  | Err why -> error "spectre-uart: {why}".
ensure why yes = if yes then Unit else error why.
