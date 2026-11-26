# Build Main and its onboard plugins. Existing user disks are preserved.
K = use "sdk/sdk".
J = use "sol/lib/json".
CLI = use "sol/lib/cli".
options = List.map (fn k -> CLI.Option k "" CLI.One) ["root","fprisc","output","arch","cc"] +
  List.map (fn k -> CLI.Option k "" CLI.Switch) ["force","run","no-compiler"].
setting name fallback = case K.need (Env.get name) of EnvText s -> if s == "" then fallback else s | EnvMissing -> fallback.
execute root env argv = status = K.need (Proc.streamNow (ProcessSpec argv root env "" 0));
  if status == 0 then Unit else Script.abort status.
field lines key = case List.filter (fn line -> Str.startsWith "{key} = " line) lines of
    [line] -> Str.trim (substr line (Str.len key+3) (Str.len line - Str.len key - 3))
  | _ -> error "profile needs one {key} field".
profileBuild argv =
  parsed = K.need (CLI.parse options argv);
  _ = K.check "unexpected profile operands" (CLI.operands parsed == []);
  root = K.realpath (CLI.valueOr "." "root" parsed);
  fpr = K.realpath (CLI.valueOr (setting "FPRISC_ROOT" (if K.isFile "{root}/fprisc.path" then Str.trim (K.readText "{root}/fprisc.path") else "{root}/../fprisc")) "fprisc" parsed);
  output = CLI.valueOr "{root}/build/profiles/Main" "output" parsed;
  _ = K.mkdirs output;
  out = K.realpath output;
  arch = CLI.valueOr "" "arch" parsed; cc = CLI.valueOr "" "cc" parsed;
  _ = K.check "expected a64, x64 or rv64" (List.has arch ["","a64","x64","rv64"]);
  _ = K.check "--cc requires --arch=rv64" (cc == "" or arch == "rv64");
  env = [("FPRISC_ROOT",fpr),("FPR_HOME",root),("FPR_PATH","{root}/programs:{fpr}"),("FPR_FOREIGN","{root}/core/foreign.fpr"),("XDG_CACHE_HOME","{out}/cache")];
  lines = List.filter (fn line -> line != "" and not (Str.startsWith "#" line)) (List.map Str.trim (Str.lines (K.readText "{root}/profiles/Main.toml")));
  source = K.need (J.parse (field lines "entry") |>? J.text);
  _ = K.check "Main source is missing; run git submodule update --init" (K.isFile "{root}/{source}");
  profile = Str.join "\n" lines;
  begin = Str.find 91 profile; end = Str.find 93 profile;
  _ = K.check "profile needs an apps array" (begin >= 0 and end > begin);
  apps = List.map (fn value -> K.need (J.text value)) (K.need (J.parse (substr profile begin (end - begin+1)) |>? J.items));
  runner = setting "SOL" "sol";
  buildEnv = (if arch == "" then [] else [("APP_HOST",arch)]) + (if cc == "" then [] else [("QOS_RV64_CC",cc)]) + env;
  _ = execute root env ["make","-s","fpr"];
  archives = List.map (fn app ->
    stem = K.baseName app; name = substr stem 0 (Str.len stem - 4); archive = "{out}/{name}.qa";
    _ = execute root buildEnv [runner,"{root}/tools/build-checkout-app.sol","plugin",app,archive,"{out}/plugin-{name}"];
    archive) apps;
  _ = execute root buildEnv [runner,"{root}/tools/build-checkout-app.sol","app",source,"{out}/main.qa","{out}/shell-build",""];
  disk = "{out}/Main.disk";
  preserve = if K.exists disk then ["--preserve"] else [];
  _ = execute root env ([runner,"{root}/tools/mkdisk.sol"]+preserve+[disk,"32"]+archives);
  _ = K.writeText "{out}/.target" "{if arch == "" then "host" else arch}:{cc}\n";
  _ = print "Main Profile: {out}/main.qa";
  if CLI.flag "run" parsed then
    _ = K.check "cross-built profiles cannot run on this host" (arch == "" or arch == (if K.command ["uname","-m"] == "riscv64" then "rv64" else "a64"));
    _ = execute root env [runner,"{root}/tools/build-host.sol","gl"];
    compiler = if CLI.flag "no-compiler" parsed then [] else [startCompiler root fpr out env runner];
    _ = execute out (("FPR_DISK",disk)::env) ["{root}/qos/qosp-gl","--yes","{out}/main.qa"];
    _ = List.map (fn job -> Proc.cancel job) compiler;
    Unit
  else Unit.
# The Editor builds through the compiler daemon (tools/fprd/QosFprd.hs) on the
# socket qosp's Sys.compile uses; built here once, stopped when qosp exits.
startCompiler root fpr out env runner =
  daemon = "{out}/qos-fprd";
  _ = (if K.isFile daemon then Unit else execute root env [runner,"{root}/tools/fprd/build.sol",daemon,fpr]);
  sock = setting "FPRD_SOCK" "/tmp/fprd.sock";
  spec = ProcessSpec [daemon,"daemon","--socket",sock,"--work","{out}/fprd"] root (("SOL",runner)::env) "" 0;
  K.need (Proc.start (PipelineSpec [spec] (PipeBytes (Bytes.empty Unit)) PipeDiscard PipeOutputInherit 0 PipeFail)).
> profileBuild (args Unit).
