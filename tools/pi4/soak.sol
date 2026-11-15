# Observe the installed QOS process without restarting it or changing its disk.
#   sol tools/pi4/soak.sol --host HOST --output DIR [--seconds N] [--interval S] [--max-growth-mib M]
# Samples the process over SSH every S seconds (default 30) for N (default
# 1800): pid, RSS and anonymous memory (smaps_rollup), V3D buffer objects,
# temperature, frequency and the service state. A changed pid, lost
# readiness, a failed sample, or RSS growing more than M MiB (default 16) after
# the first three samples fails the run. It measures residency, not the
# runtime's logical live allocation, and asserts no workload.
unsafe program.
R = use "remote".
J = use "sol/lib/json".
CLI = use "sol/lib/cli".
options = List.map (fn k -> CLI.Option k "" CLI.One) ["host","output","seconds","interval","max-growth-mib","ready-file"].
clockNow u = parseInt (R.local ["date","+%s"]).
probe ready = "set -e; p=$(cat " + R.q ready + "); case \"$p\" in ''|*[!0-9]*) exit 2;; esac; echo \"pid $p\"; "
  + "awk '/^Rss:/\{print \"rss \" $2} /^Anonymous:/\{print \"anon \" $2}' /proc/$p/smaps_rollup; "
  + "echo \"temp $(cat /sys/class/thermal/thermal_zone0/temp)\"; echo \"freq $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)\"; "
  + "echo \"bo $(grep -s -E '^(allocated|shared)' /sys/kernel/debug/dri/0/bo_stats | tr -s ' \\n' ' ')\"; echo \"state $(cat /var/run/qosp/state)\"".
value key text = case List.filter (fn l -> Str.startsWith "{key} " l) (Str.lines text) of
    l :: _ -> Str.slice l (Str.len key + 1) (Str.len l) | [] -> error "sample lacks {key}: {text}".
sampleLoop ctx until pid n acc =
  raw = R.ssh ctx.host 20 (probe ctx.ready);
  _ = R.write "{ctx.output}/sample-{n}.txt" raw;
  current = value "pid" raw;
  _ = (if pid == "" or current == pid then Unit else error "the application pid changed from {pid} to {current}");
  rss = parseInt (value "rss" raw);
  _ = print "sample {n}: pid {current} RSS {rss} KiB {value "bo" raw}";
  next = rss :: acc;
  if clockNow Unit >= until then (current, List.rev next) else
    _ = sleepMs (ctx.interval * 1000); sampleLoop ctx until current (n + 1) next.
observe parsed =
  host = CLI.valueOr "" "host" parsed; output = CLI.valueOr "" "output" parsed;
  _ = (if host == "" or output == "" then error "usage: sol tools/pi4/soak.sol --host HOST --output DIR [--seconds N]" else Unit);
  seconds = parseInt (CLI.valueOr "1800" "seconds" parsed);
  interval = parseInt (CLI.valueOr "30" "interval" parsed);
  growth = parseInt (CLI.valueOr "16" "max-growth-mib" parsed);
  _ = R.local ["mkdir","-p",output];
  ctx = {host = host, output = output, interval = interval, ready = CLI.valueOr "/var/run/qosp/ready" "ready-file" parsed};
  (pid, samples) = sampleLoop ctx (clockNow Unit + seconds) "" 0 [];
  steady = List.drop 3 samples;
  low = if steady == [] then 0 else List.fold (fn m x -> if x < m then x else m) (steady ! 0) steady;
  high = List.fold (fn m x -> if x > m then x else m) 0 steady;
  _ = (if high - low > growth * 1024 then error "RSS grew {high - low} KiB after warmup (limit {growth} MiB)" else Unit);
  _ = R.write "{output}/complete.json" (J.pretty (J.JObj [("passed",J.JBool True),("pid",J.JStr pid),("seconds",J.JNum seconds),
    ("samples",J.JNum (List.len samples)),("rss_kib",J.JArr (List.map (fn x -> J.JNum x) samples)),("steady_growth_kib",J.JNum (high - low)),
    ("scope",J.JStr "same ready process, successful memory samples; no workload assertions")]) + "\n");
  print "soak: pid {pid} held for {seconds} s, {List.len samples} samples, steady RSS {low}..{high} KiB".
> observe (R.need (CLI.parse options (args Unit))).
