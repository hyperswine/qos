# Exercise an isolated, matching Main bundle on a Pi with key input; the
# installed session is not touched. The remote directory holds runner,
# qosp-es, main.qa and Main.disk; both boots use a copy of Main.disk on the
# SD-backed /var/lib/qosp.
#   sol tools/pi4/main-soak.sol --host HOST --remote-dir DIR --output DIR
#       [--seconds N] [--harts 1|4] [--max-growth-mib M] [--viewport WxH]
# Boot 1 cycles the launcher through Files, Logs and the Browser (scroll keys,
# both text viewports) until N seconds, samples RSS after every cycle, then
# stops with SIGTERM and requires a clean shutdown. Boot 2 restarts on the same
# disk and requires the ready line and a clean shutdown again. RSS after the
# first three samples may grow by at most M MiB (default 16). Residency is
# sampled, not reachability: this does not prove the absence of a logical leak.
unsafe program.
R = use "remote".
J = use "sol/lib/json".
CLI = use "sol/lib/cli".
options = List.map (fn k -> CLI.Option k "" CLI.One) ["host","remote-dir","output","seconds","harts","max-growth-mib","viewport","shortcuts"].
clockNow u = parseInt (R.local ["date","+%s"]).
logCount ctx boot text = parseInt (Str.trim (R.ssh ctx.host 20 "grep -c -F {R.q text} {R.q ctx.work}/boot{boot}.log || true")).
bootPanicked ctx boot = Str.trim (R.ssh ctx.host 20 "grep -c -E 'PANIC|SIGSEGV' {R.q ctx.work}/boot{boot}.log || true") != "0".
awaitLog ctx boot text n tries =
  if bootPanicked ctx boot then error "boot {boot}: panic\n{R.ssh ctx.host 20 "tail -c 3000 {R.q ctx.work}/boot{boot}.log"}" else
  if logCount ctx boot text >= n then Unit else
  if tries <= 0 then error "boot {boot}: waiting for {text} #{n}\n{R.ssh ctx.host 20 "tail -c 2000 {R.q ctx.work}/boot{boot}.log"}" else
    _ = sleepMs 300; awaitLog ctx boot text n (tries - 1).
sendKeys ctx boot codes = List.map (fn code ->
    # opened read-write so a dead candidate cannot hang the writer
    _ = R.ssh ctx.host 20 "printf '{R.keyPress code}' 1<> {R.q ctx.work}/keys{boot}";
    sleepMs 200) codes.
bootStart ctx boot seconds stop =
  w = ctx.work;
  view = if ctx.viewport == "" then "" else " FPR_GFX_SIZE={R.q ctx.viewport}";
  _ = R.ssh ctx.host 20 ("cd {R.q w} && mkfifo {R.q w}/keys{boot} && FPR_HARTS={ctx.harts} FPR_HEAP_MB=256 QOSP_ARENA_MB=256 FPR_PORT=0"
    + " FPR_EVDEV={R.q w}/keys{boot}{view} QOSP_READY_FILE={R.q w}/ready{boot} FPR_DISK={R.q ctx.store}/Main.disk"
    + " {R.q ctx.base}/runner {seconds + 60} {stop} {R.q w}/boot{boot}.log {R.q ctx.base}/qosp-es --yes {R.q ctx.base}/main.qa"
    + " > {R.q w}/boot{boot}.json 2> {R.q w}/boot{boot}.err < /dev/null &");
  awaitLog ctx boot "Main Profile ready ({ctx.shortcuts} shortcuts," 1 100.
bootFinish ctx boot tries =
  raw = Str.trim (R.ssh ctx.host 20 "cat {R.q ctx.work}/boot{boot}.json");
  if raw == "" then (if tries <= 0 then error "boot {boot}: runner gave no result" else _ = sleepMs 500; bootFinish ctx boot (tries - 1)) else
    log = R.ssh ctx.host 30 "cat {R.q ctx.work}/boot{boot}.log";
    _ = R.write "{ctx.output}/boot{boot}.log" log;
    _ = R.write "{ctx.output}/boot{boot}.json" raw;
    meta = R.need (J.parse raw);
    _ = (if R.number "exit" meta == 0 and R.number "signal" meta == 0 and not (R.flag "timeout" meta) and not (R.flag "killed" meta) then Unit
      else error "boot {boot}: {raw}");
    _ = (if Str.contains "[gfx] EGL" log and Str.contains "V3D" log then Unit else error "boot {boot}: the Pi's EGL/V3D backend was not exercised");
    _ = (if Str.contains "qosp: shutdown complete" log then Unit else error "boot {boot}: no clean shutdown");
    raw.
sampleRss ctx = parseInt (Str.trim (R.ssh ctx.host 20 "p=$(cat {R.q ctx.work}/ready1) && awk '/^VmRSS:/\{print $2}' /proc/$p/status")).
soakCycle ctx until n samples =
  if clockNow Unit >= until then List.rev samples else
    _ = sendKeys ctx 1 [1,102,106,28];
    _ = awaitLog ctx 1 "shell: open files" (n + 1) 60;
    _ = sendKeys ctx 1 [109,102,1,102,106,106,28];
    _ = awaitLog ctx 1 "shell: open logs" (n + 1) 60;
    _ = sendKeys ctx 1 [107,102,1,102,106,106,106,106,106,106,28];
    _ = awaitLog ctx 1 "shell: open browser" (n + 1) 60;
    _ = sendKeys ctx 1 [108,28,1,102];
    kib = sampleRss ctx;
    _ = print "cycle {n + 1}: RSS {kib} KiB";
    soakCycle ctx until (n + 1) (kib :: samples).
soak parsed =
  host = CLI.valueOr "" "host" parsed; base = CLI.valueOr "" "remote-dir" parsed; output = CLI.valueOr "" "output" parsed;
  _ = (if host == "" or base == "" or output == "" then error "usage: sol tools/pi4/main-soak.sol --host HOST --remote-dir DIR --output DIR" else Unit);
  seconds = parseInt (CLI.valueOr "600" "seconds" parsed);
  harts = parseInt (CLI.valueOr "4" "harts" parsed);
  growth = parseInt (CLI.valueOr "16" "max-growth-mib" parsed);
  shortcuts = parseInt (CLI.valueOr "10" "shortcuts" parsed);
  _ = (if seconds < 60 or not (List.has harts [1,4]) then error "seconds must be at least 60 and harts 1 or 4" else Unit);
  _ = R.local ["mkdir","-p",output];
  tag = R.stamp Unit;
  work = "{base}/soak-{tag}"; store = "/var/lib/qosp/check-main-soak-{tag}";
  before = R.ssh host 20 "cat /var/run/qosp/state";
  hashes = R.ssh host 20 "cd {R.q base} && sha256sum qosp-es main.qa Main.disk";
  _ = R.ssh host 30 "mkdir {R.q work} {R.q store} && cp {R.q base}/Main.disk {R.q store}/Main.disk";
  ctx = {host = host, base = base, work = work, store = store, output = output, harts = harts, viewport = CLI.valueOr "" "viewport" parsed, shortcuts = shortcuts};
  started = clockNow Unit;
  _ = bootStart ctx 1 seconds seconds;
  samples = soakCycle ctx (started + seconds - 20) 0 [];
  _ = bootFinish ctx 1 120;
  steady = List.drop 3 samples;
  low = if steady == [] then 0 else List.fold (fn m x -> if x < m then x else m) (steady ! 0) steady;
  high = List.fold (fn m x -> if x > m then x else m) 0 steady;
  _ = (if List.len steady < 2 then error "fewer than two samples after warmup ({List.len samples} cycles)" else Unit);
  _ = (if high - low > growth * 1024 then error "RSS grew {high - low} KiB after warmup (limit {growth} MiB)" else Unit);
  _ = bootStart ctx 2 30 20;
  _ = bootFinish ctx 2 120;
  after = R.ssh host 20 "cat /var/run/qosp/state";
  _ = (if after == before then Unit else error "the installed session changed: {before} -> {after}");
  result = J.JObj [("passed",J.JBool True),("seconds",J.JNum seconds),("harts",J.JNum harts),("cycles",J.JNum (List.len samples)),
    ("rss_kib",J.JArr (List.map (fn x -> J.JNum x) samples)),("steady_growth_kib",J.JNum (high - low)),("bundle_hashes",J.JStr hashes),
    ("installed_session",J.JStr (Str.trim before)),("work",J.JStr work),("store",J.JStr store),
    ("scope",J.JStr "isolated Main with key input, two boots and clean shutdowns; sampled residency, not reachability")];
  _ = R.write "{output}/result.json" (J.pretty result + "\n");
  print "main soak: {List.len samples} cycles over {seconds} s, steady RSS {low}..{high} KiB, both boots shut down cleanly".
> soak (R.need (CLI.parse options (args Unit))).
