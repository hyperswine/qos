# Physical runtime qualification on a Pi 4B: the bundle tools/pi4-build.sol
# builds, run case by case under runner.c (deadlines, CPU/RSS/thermal samples)
# in isolated directories over public-key SSH. Durability cases use separate
# files on the SD-backed /var/lib/qosp. No reboot, package replacement, power
# cut or credential change; the installed session is not touched.
#   sol tools/pi4/check.sol --host HOST --bundle DIR --output DIR [--soak-seconds N]
#                           [--skip-runtime] [--skip-bench] [--skip-soak]
# The forwarded four-peer binary TCP case (nettransport) of the retired
# check.py is not run: it needs concurrent socket clients on this side.
unsafe program.
R = use "remote".
J = use "sol/lib/json".
CLI = use "sol/lib/cli".
options = List.map (fn k -> CLI.Option k "" CLI.One) ["host","bundle","output","soak-seconds"] +
  List.map (fn k -> CLI.Option k "" CLI.Switch) ["skip-runtime","skip-bench","skip-soak"].
plain = {expected = "", exact = False, contains = [], forbidden = [], exit = 0, env = [], args = [], deadline = 60, stop = 0, disk = ""}.
# one case: answers True when every check holds
runCase ctx c name exe harts =
  if not (List.has exe ctx.present) then
    _ = print "SKIP {name}: {exe} is not in the bundle";
    _ = R.write "{ctx.output}/{name}.json" (J.render (J.JObj [("name",J.JStr name),("skipped",J.JBool True)]));
    True
  else runPresent ctx c name exe harts.
runPresent ctx c name exe harts =
  host = ctx.host; remote = ctx.remote;
  dir = "{remote}/{name}";
  disk = if c.disk == "" then "{dir}/disk" else c.disk;
  values = List.append [("FPR_HARTS","{harts}"),("FPR_PORT","0"),("FPR_DISK",disk),("QOSP_READY_FILE","{dir}/ready")] c.env;
  program = if Str.endsWith ".qa" exe then ["{remote}/qosp-es","--yes","{remote}/{exe}"] else List.append ["{remote}/{exe}"] c.args;
  argv = List.concat [["{remote}/runner","{c.deadline}","{c.stop}","{dir}/run.log","env"],List.map (fn kv -> (k,v) = kv; "{k}={v}") values,program];
  raw = R.ssh host (c.deadline + 30) "mkdir -p {R.q dir}; cd {R.q dir}; {R.words argv}";
  log = R.ssh host 60 "cat {R.q dir}/run.log";
  _ = R.write "{ctx.output}/{name}.log" log;
  meta = R.need (J.parse (Str.trim raw));
  seconds = R.number "seconds" meta;
  checks = List.concat [
    [R.number "exit" meta == c.exit, R.number "signal" meta == 0, not (R.flag "timeout" meta), not (R.flag "killed" meta)],
    (if c.exact then [log == c.expected] else []),
    List.map (fn t -> Str.contains t log) c.contains,
    List.map (fn t -> not (Str.contains t log)) c.forbidden,
    (if c.stop > 0 then [R.flag "stop_requested" meta, seconds < c.stop + 6] else []),
    (if c.exit == 0 then [not (Str.contains "FAILED" log), not (Str.contains "fatal SIG" log)] else [])];
  passed = List.all (fn x -> x) checks;
  _ = print "{if passed then "PASS" else "FAIL"} {name}: {seconds}s RSS={R.number "max_rss_kib" meta}KiB exit={R.number "exit" meta} signal={R.number "signal" meta}";
  _ = (if passed then Unit else print (Str.slice log (if Str.len log > 5000 then Str.len log - 5000 else 0) (Str.len log)));
  _ = R.write "{ctx.output}/{name}.json" (J.render (J.JObj [("name",J.JStr name),("executable",J.JStr exe),("harts",J.JNum harts),("passed",J.JBool passed),("runner",meta)]));
  passed.
exactCase ctx name exe harts text = runCase ctx {plain | exact = True, expected = text} name exe harts.
containsCase ctx name exe harts required = runCase ctx {plain | contains = required} name exe harts.
runtime ctx harts =
  h = "-h{harts}";
  exact = [("strprims", R.readLocal "{ctx.bundle}/strprims.expected"),
    ("killblocked","killblocked: 1500 more kills of blocked actors cost under 32 MiB\n"),
    ("deadmail","deadmail: 900 more deaths with 49 KiB of mail unread each cost under 16 MiB\n"),
    ("autodrop2","autodrop2: 3000 direct destructures cost under 32 MiB; 3000 Result-wrapped receives cost under 32 MiB\n"),
    ("sleepwait","waiter got 7\nmain got 1\n"),
    ("taskstress","shastress: 40\n"),
    ("deadlines","deadlines: selective/FIFO/overflow/death/admission/stale/late-reply contracts HOLDS\n"),
    ("mvudeadlines","mvudeadlines: live dimensions/input/ports/render/worker deadlines and watcher cleanup HOLDS\n"),
    ("mvufailure","mvufailure: admission/death/input/ports/worker Results and subsequent healthy run HOLDS\n"),
    ("mvuscoped","mvuscoped: caller state survives; 20000 frames cost under 4 MiB\n"),
    ("typedvector","typed: 2 7 2.5 ok 2.25 3 True\n"),
    ("files","files: True False 8 [one\ntwo\n]\n"),
    ("veccaps","affine: sum=10000000000 grew=0 B; above: kept=49999 sum=7499899999 grew=0 B\nbool capture unboxed: 10 0\nnine-field record map: sum=5546500 grew=0 B\nrecord filter: kept=559 sum=402480 last.f8=1007 grew=0 B\n"),
    ("vecwide","w2: at3=9 kept=8 sum=8147 echoed=8147\nw4: at3=30 kept=8 sum=8490 echoed=8490\nw8: at3=108 kept=8 sum=9764 echoed=9764\nw9: at3=135 kept=8 sum=10205 echoed=10205\nw32: at3=1584 kept=8 sum=33872 echoed=33872\nw65: at3=6435 kept=8 sum=113105 echoed=113105\nw128: at3=24768 kept=8 sum=412544 echoed=412544\nfloat record: n=4 x=1.5 y=2.25 k=2\none: 3\n")];
  contains = [("taskfailure",["taskfailure: death/sibling cancellation/deadline/order/limit/inbox/cleanup contracts HOLDS"]),
    ("arenamigrate",["arenamigrate: nested arenas and loopWith survive; migrations="]),
    ("fixedheap",["HOLDS","local grant exhausted","scratch arenas require separate admission","reset blocked by escaped data"]),
    ("sleepwake",["sleepwake: alive"]),
    ("fvec2",["kept=999","FLOATVEC2 HOLDS"]),
    ("fmath",["ok log2-pow2","ok pythagorean"]),
    ("actors",["actor demo done"]),
    ("bigheap",["bigheap: 72000006000000"])];
  # mvuscoped's 20000 cross-actor frames take about 75 s at the powersave
  # governor's 600 MHz (the retired driver could switch to performance)
  a = List.map (fn p -> (n,t) = p; runCase ctx {plain | exact = True, expected = t, deadline = (if n == "mvuscoped" then 180 else 60)} "{n}{h}" n harts) exact;
  b = List.map (fn p -> (n,t) = p; containsCase ctx "{n}{h}" n harts t) contains;
  long = "PANIC [actor 0]: long:{Str.join "" (List.map (fn i -> "0123456789") (List.range 1 30))}:end ***";
  simd = Str.join "" (List.map (fn i -> n = 99 - i; "simd-int: {n} {n * (n - 1) / 2 + 7 * n}\n") (List.range 0 99));
  c = [runCase ctx {plain | exact = True, expected = "in range: True True\nvalue: 0\n", args = ["63","value"]} "bits-valid{h}" "bitrange" harts,
    runCase ctx {plain | contains = ["BITSHIFTL: shift must be 0..63"], exit = 1, args = ["64","inline"]} "bits-shift{h}" "bitrange" harts,
    runCase ctx {plain | contains = ["BITSET: bit index must be 0..63"], exit = 1, args = ["-1","value"]} "bits-index{h}" "bitrange" harts,
    runCase ctx {plain | contains = [long], exit = 1} "longpanic{h}" "longpanic" harts,
    runCase ctx {plain | contains = ["heap exhausted"], exit = 1, env = [("FPR_HEAP_MB","64")]} "heap-limit{h}" "bigheap" harts,
    runCase ctx {plain | contains = ["accumulator: 200000","recursion: 200000","stack overflow"], exit = 1, env = [("FPR_STACK_MAX_MB","64")]} "stack-limit{h}" "overflow" harts,
    exactCase ctx "vecsimd{h}" "vecsimd_int" harts simd];
  List.concat [a,b,c].
applications ctx harts =
  h = "-h{harts}";
  remote = ctx.remote; persistent = ctx.persistent; host = ctx.host;
  holds = List.map (fn name ->
      fault = (if name == "blocklifecyclep" then [("QOS_BLK_TEST_DELAY_US","800000"),("QOS_BLK_TEST_DELAY_READS","1"),("QOS_BLK_DEADLINE_MS","300")]
        else if name == "blockmemory" then [("QOSP_ARENA_MB","64")] else []);
      runCase ctx {plain | contains = ["HOLDS"], env = fault} "qos-{name}{h}" "{name}.qa" harts)
    ["blockportable","blocknamespace","blocklifecyclep","blockmemory","filesshutdown","gfxshare","guishell","panemvu","appsession","appjobs","appsessionmemory","shelllayout","netactor","netactorstart"];
  gfx = runCase ctx {plain | deadline = 120, contains = ["gfxmemory: 100000 frames retain under 2 MiB; backend state survives"]} "qos-gfxmemory{h}" "gfxmemory.qa" harts;
  filesDisk = "{persistent}/files-{harts}.disk";
  files = List.map (fn p -> (boot,size) = p;
      runCase ctx {plain | disk = filesDisk, contains = ["filessvc: HOLDS","filessvc: replay lengths {size} {size}"]} "qos-files{h}-boot{boot}" "filessvc.qa" harts) [(1,6),(2,12)];
  shutDisk = "{persistent}/shutdown-{harts}.disk";
  shutdown = List.map (fn p -> (boot,line) = p;
      runCase ctx {plain | stop = 3, deadline = 12, disk = shutDisk, contains = ["portableshutdown: {line}","storage drained and flushed","qosp: shutdown complete"]} "qos-shutdown{h}-boot{boot}" "portableshutdown.qa" harts)
    [(1,"fresh"),(2,"replayed=committed")];
  faults = List.map (fn f -> (label,env,status,limit) = f;
      faultDisk = "{persistent}/{label}-{harts}.disk";
      _ = R.ssh host 30 "if [ -e {R.q shutDisk} ]; then cp {R.q shutDisk} {R.q faultDisk}; fi";
      runCase ctx {plain | stop = 3, deadline = 12, disk = faultDisk, exit = status, env = List.append env [("QOSP_SHUTDOWN_MS",limit)],
          contains = (if status == 1 then ["qosp: shutdown failed"] else []), forbidden = ["qosp: shutdown complete"]} "qos-{label}{h}" "portableshutdown.qa" harts)
    [("flush-error",[("QOS_BLK_TEST_FAIL_FLUSH_AT","4")],1,"5000"),
     ("flush-stall",[("QOS_BLK_TEST_FLUSH_DELAY_AT","4"),("QOS_BLK_TEST_FLUSH_DELAY_US","2000000")],124,"250")];
  qsysDisk = "{persistent}/qsys-{harts}.disk";
  _ = R.ssh host 30 "if [ -e {R.q remote}/qsys.disk ]; then cp {R.q remote}/qsys.disk {R.q qsysDisk}; fi";
  plugins = List.map (fn boot -> runCase ctx {plain | disk = qsysDisk, contains = ["qsys: boot #{boot}; 2 apps [plugmini,plughello];","ping=pong from a .qa read off qosp.disk",
      "hello=plughello: the second sub-slot; 21+21=42;","note={boot * 3}B;"]} "qos-plugins{h}-boot{boot}" "qsys.qa" harts) [1,2];
  List.concat [holds,[gfx],files,shutdown,faults,plugins].
gpu ctx =
  a = runCase ctx {plain | contains = ["V3D 4.2.14","gfx smoke: ppm rc=0"]} "gpu-readback" "gfxsmoke.qa" 4;
  _ = R.copyFrom ctx.host "/tmp/gfx-smoke.ppm" "{ctx.output}/gpu-readback.ppm";
  b = runCase ctx {plain | deadline = 120, contains = ["V3D 4.2.14","gfxheadless: 5000 frames HOLDS"]} "gpu-5000-frames" "gfxheadless.qa" 4;
  _ = R.copyFrom ctx.host "/tmp/gfx-headless.ppm" "{ctx.output}/gpu-5000-frames.ppm";
  [a,b].
benchmarks ctx = List.concat (List.map (fn program ->
    expected = R.readLocal "{ctx.bundle}/bench-{program}.expected";
    List.concat (List.map (fn harts -> List.map (fn trial ->
        runCase ctx {plain | exact = True, expected = expected, deadline = 120} "bench-{program}-h{harts}-{trial}" "bench-{program}" harts) [1,2,3])
      (if program == "xpingpong" then [4] else [1,4])))
  ["fib","sha","pingpong","xpingpong","nbody","vecread"]).
soaks ctx seconds = List.map (fn harts ->
    name = "main-soak-h{harts}"; dir = "{ctx.remote}/{name}";
    _ = R.ssh ctx.host 30 "mkdir -p {R.q dir}; if [ -e {R.q ctx.remote}/Main.disk ]; then cp {R.q ctx.remote}/Main.disk {R.q dir}/disk; fi";
    runCase ctx {plain | stop = seconds, deadline = seconds + 12, contains = ["Main Profile ready","qosp: shutdown complete"]} name "main.qa" harts) [1,4].
qualify parsed =
  host = CLI.valueOr "" "host" parsed;
  bundle = CLI.valueOr "" "bundle" parsed;
  output = CLI.valueOr "" "output" parsed;
  _ = (if host == "" or bundle == "" or output == "" then error "usage: sol tools/pi4/check.sol --host HOST --bundle DIR --output DIR" else Unit);
  soakSeconds = parseInt (CLI.valueOr "300" "soak-seconds" parsed);
  _ = R.local ["mkdir","-p",output];
  model = R.ssh host 10 "tr -d '\\000' < /proc/device-tree/model";
  _ = (if Str.contains "Raspberry Pi 4 Model B" model then Unit else error "expected a Pi 4B, got {model}");
  _ = R.write "{output}/inventory.txt" (model + "\n" + R.ssh host 20 "uname -a; cat /proc/meminfo; df -k / /tmp; cat /sys/class/thermal/thermal_zone0/temp; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor; cat /var/run/qosp/state");
  tag = R.stamp Unit;
  remote = "/tmp/qosp-check-{tag}"; persistent = "/var/lib/qosp/check-{tag}";
  archive = "{output}/bundle.tar";
  _ = R.local ["sh","-c","cd \"$0\" && find . -maxdepth 1 -type f -print | sort | tar cf \"$1\" -T -",bundle,archive];
  _ = R.copyTo host archive "/tmp/qosp-check-{tag}.tar";
  _ = R.ssh host 120 "mkdir -p {R.q remote} {R.q persistent} && tar xf {R.q remote}.tar -C {R.q remote} && rm {R.q remote}.tar";
  present = Str.lines (R.local ["sh","-c","cd \"$0\" && find . -maxdepth 1 -type f | sed 's|^./||'",bundle]);
  ctx = {host = host, remote = remote, persistent = persistent, output = output, bundle = bundle, present = present};
  skipRuntime = CLI.flag "skip-runtime" parsed;
  results = List.concat [
    (if skipRuntime then [] else List.concat [runtime ctx 1, runtime ctx 4, applications ctx 1, applications ctx 4, gpu ctx]),
    (if CLI.flag "skip-bench" parsed then [] else benchmarks ctx),
    (if CLI.flag "skip-soak" parsed then [] else soaks ctx soakSeconds)];
  _ = R.write "{output}/kernel-after.txt" (R.ssh host 20 "dmesg | tail -200; cat /var/run/qosp/state");
  passed = List.len (List.filter (fn x -> x) results);
  _ = print "{passed}/{List.len results} cases passed or skipped (skips are listed above as SKIP; remote {remote}, persistent {persistent})";
  if passed == List.len results then Unit else Script.abort 1.
> qualify (R.need (CLI.parse options (args Unit))).
