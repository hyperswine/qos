# The Spectre prompt from Sol: each command is one run of spectre-uart
# (hal/spectre/tools/spectre-uart.c), which owns the serial port.
# SPECTRE_UART names the port, SPECTRE_UART_TOOL the built helper.
unsafe program.
B = use "sol/lib/build".
port = B.setting "SPECTRE_UART" "/dev/cu.usbserial-20250303171".
tool = B.setting "SPECTRE_UART_TOOL" "spectre-uart".
prompt = "qos> ".
uart ops = case Proc.runNow (ProcessSpec (tool :: port :: ops) "" [] "" 0) of
    Ok (ProcessResult 0 out _) -> out
  | Ok (ProcessResult code out err) -> error "spectre-uart exited {code}: {err}{out}"
  | Err why -> error "spectre-uart: {why}".
ensure why yes = if yes then Unit else error why.
# type a line, wait for the prompt: what came back, the echo and the prompt included
frame seconds line = uart ["send-line", line, "expect", prompt, "{seconds}"].
# the rows between the echoed line and the prompt
rowsOf line text =
  _ = ensure "the prompt did not echo the command: {text}" (Str.startsWith "{line}\n" text and Str.endsWith prompt text);
  Str.lines (Str.slice text (Str.len line + 1) (Str.len text - Str.len prompt)).
command seconds line = rowsOf line (frame seconds line).
# rows before the first prompt, wherever the echo fell
loose seconds line = text = frame seconds line;
  at = Str.indexOf prompt text;
  _ = ensure "no prompt: {text}" (at >= 0);
  Str.lines (Str.slice text 0 at).
has row rows = List.any (fn r -> r == row) rows.
expectRow seconds line row = rows = loose seconds line; ensure "{line}: expected the row {row}, got {rows}" (has row rows).
# "running; yields N" -> N
yieldsIn rows = case List.filter (fn r -> Str.startsWith "running; yields " r) rows of
    r :: _ -> (case Try.parseInt (Str.slice r 16 (Str.len r)) of Ok n -> n | Err _ -> error "malformed yields row: {r}")
  | [] -> error "no running job in {rows}".
# install a package under a name unless it is there, and read it back
install seconds name image =
  rows = loose seconds "create {name} {image}";
  _ = ensure "create {name}: {rows}" (has "created {name}" rows or has "already exists" rows);
  expectRow seconds "cat {name}" image.
wake seconds = uart ["send-hex", "0a", "expect", prompt, "{seconds}"].
# CPU reset: autonomous SD boot, no install and no image upload
reset seconds = text = uart ["send-hex", "03", "expect", prompt, "{seconds}"];
  _ = ensure "autonomous SD boot marker missing: {text}" (Str.contains "Spectre SD boot OK" text);
  text.
sleepMs ms = Sys.sleepUs (ms * 1000).
