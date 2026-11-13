# Contributor build and packaging. Make supplies compiler/link mechanisms;
# Sol owns paths, manifests, plugins and bundles. No shell command strings.
K = use "sdk/sdk".
CLI = use "sol/lib/cli".
J = use "sol/lib/json".
setting name fallback = case K.need (Env.get name) of EnvText value -> if value == "" then fallback else value | EnvMissing -> fallback.
options = List.map (fn name -> CLI.Option name "" CLI.One) ["root","fprisc","harts","out","name","disk-mb"] +
  [CLI.Option "plugin" "" CLI.Many] + List.map (fn name -> CLI.Option name "" CLI.Switch) ["bundle","gfx","no-plugins","verbose","help"].
invoke root env argv =
  status = K.need (Proc.streamNow (ProcessSpec argv root env "" 0));
  if status == 0 then Unit else Script.abort status.
hostBuild root env gfx =
  name = if gfx then "qosp-gl" else "qosp";
  if K.isFile "{root}/.installed" then K.check "installed SDK has no {name}" (K.isFile "{root}/qos/{name}")
  else invoke "{root}/qos" env ["make","-s",if gfx then "portable-gl" else "portable"].
compilerBuild root env = if K.isFile "{root}/.installed" then K.check "installed SDK has no compiler" (K.isFile "{root}/toolchain/fpr") else invoke root env ["make","-s","fpr"].
identifier name = Str.len name > 0 and Str.len name <= 64 and
  List.all (fn c -> (c >= 65 and c <= 90) or (c >= 97 and c <= 122) or (c >= 48 and c <= 57) or List.has c [45,46,95]) (Str.codes name)
  and not (Str.startsWith "." name) and not (Str.startsWith "-" name) and not (Str.contains ".." name).
stripComment raw =
  (_,_,_,codes) = List.fold (fn state c ->
    (quote,escaped,done,out) = state;
    if done then state else if escaped then (quote,False,False,c::out) else
    if quote == 34 and c == 92 then (quote,True,False,c::out) else
    if quote != 0 and c == quote then (0,False,False,c::out) else
    if quote == 0 and (c == 34 or c == 39) then (c,False,False,c::out) else
    if quote == 0 and c == 35 then (0,False,True,out) else (quote,False,False,c::out)) (0,False,False,[]) (Str.codes raw);
  Str.join "" (List.map Str.fromCode (List.rev codes)).
# The contributor manifest has string-valued [app] and [build] fields.
# JSON's string decoder handles quoted escapes; literal TOML strings pass
# through unchanged. Refuse unsupported values instead of silently guessing.
manifest path =
  (_,pairs) = List.fold (fn state raw ->
    (section,entries) = state; line = Str.trim (stripComment raw);
    if line == "" or Str.startsWith "#" line then state else
    if Str.startsWith "[" line then
      _ = K.check "unsupported contributor manifest table: {line}" (List.has line ["[app]","[build]"]);
      (substr line 1 (Str.len line - 2),entries)
    else
      equal = Str.find 61 line;
      _ = K.check "manifest assignment expected: {line}" (equal > 0 and section != "");
      key = section+"."+Str.trim (substr line 0 equal);
      _ = K.check "duplicate manifest field: {key}" (not (List.any (fn p -> (k,_) = p; k == key) entries));
      value = Str.trim (substr line (equal+1) (Str.len line - equal - 1));
      decoded = if Str.startsWith "\"" value then K.need (J.parse value |>? J.text) else
        if Str.startsWith "'" value and Str.endsWith "'" value then substr value 1 (Str.len value - 2) else error "manifest values must be quoted strings: {key}";
      (section,entries+[(key,decoded)])) ("",[]) (Str.lines (K.readText path));
  lookup = fn key -> fn fallback -> case List.filter (fn p -> (k,_) = p; k == key) pairs of [(_,v)] -> v | [] -> fallback | _ -> error "duplicate manifest field";
  id = lookup "app.id" ""; name = lookup "app.name" id; version = lookup "app.version" "1";
  _ = K.check "invalid app id" (identifier id);
  _ = K.check "desktop projects use the installed qos build command" (lookup "app.kind" "" != "desktop");
  _ = K.check "only qos-portable contributor projects are supported" (lookup "build.target" "qos-portable" == "qos-portable");
  _ = K.check "build.entry is required" (lookup "build.entry" "" != "");
  _ = List.map (fn value -> K.check "unsafe/empty manifest name or version" (value != "" and not (List.any (fn c -> List.has c [34,92,36,96,10,13]) (Str.codes value)))) [name,version];
  source = K.realpath (K.parent path + "/" + lookup "build.entry" "");
  {source=source,id=id,assignments=["QA_ID={id}","QA_NAME={name}","QA_VERSION={version}"],assets=K.parent path+"/assets"}.
project arg =
  candidate = if K.isFile arg then K.parent arg+"/qos.toml" else arg+"/qos.toml";
  if K.isFile candidate then
    found = manifest candidate;
    if not (K.isFile arg) or found.source == K.realpath arg then found else
      {source=K.realpath arg,id=K.baseName arg,assignments=[],assets=""}
  else
    _ = K.check "source file or project with qos.toml required" (K.isFile arg);
    {source=K.realpath arg,id=K.baseName arg,assignments=[],assets=""}.
directives source key = List.concat (List.map (fn raw ->
  line = Str.trim (stripComment raw); prefix = "#: {key} ";
  if Str.startsWith prefix line then Str.words (substr line (Str.len prefix) (Str.len line - Str.len prefix)) else []) (Str.lines (K.readText source))).
stem path = base = K.baseName path; suffix = K.suffix base; substr base 0 (Str.len base - Str.len suffix).
package root env runner parsed arg workspace =
  item = project arg;
  declaredName = case directives item.source "name" of name::_ -> name | [] -> stem item.source;
  name = CLI.valueOr (if item.assignments == [] then declaredName else item.id) "name" parsed;
  _ = K.check "invalid package name" (identifier name);
  cwd = K.trimEnd (K.command ["pwd","-P"]);
  out = CLI.valueOr "{cwd}/dist/{name}" "out" parsed;
  _ = K.mkdirs out;
  destination = K.realpath out;
  buildDir = "{workspace}/build";
  _ = K.mkdirs buildDir;
  harts = CLI.valueOr "" "harts" parsed;
  _ = invoke root env ([runner,"{root}/tools/build-checkout-app.sol","app",item.source,"{destination}/{name}.qa",buildDir,harts] + item.assignments);
  requested = CLI.values "plugin" parsed;
  plugins = if CLI.flag "no-plugins" parsed then [] else if requested != [] then requested else directives item.source "plugins";
  pairs = List.concat (List.map (fn p ->
    source = if K.isFile p then K.realpath p else if K.isFile "{root}/{p}" then K.realpath "{root}/{p}" else K.realpath (K.parent item.source+"/{p}");
    [source,"{buildDir}/plug-{stem source}.qa"]) plugins);
  disk = if pairs == [] then "" else "{name}.disk";
  size = CLI.valueOr (case directives item.source "disk-mb" of [s] -> s | [] -> "8" | _ -> error "invalid disk-mb directive") "disk-mb" parsed;
  _ = if pairs == [] then Unit else invoke root env ([runner,"{root}/tools/build-checkout-app.sol","plugins",buildDir,"{root}/tools/mkdisk.sol","{destination}/{disk}",size] + pairs);
  _ = if item.assets != "" and K.exists item.assets then
    _ = K.command ["cp","-pR","{item.assets}/.",destination]; Unit else Unit;
  _ = List.map (fn music -> K.copy (K.parent item.source+"/{music}") "{destination}/{K.baseName music}") (directives item.source "music");
  gfx = CLI.flag "gfx" parsed or Str.endsWith "_desktop_gl" (stem item.source) or List.has "gl" (directives item.source "host");
  host = if gfx then "qosp-gl" else "qosp";
  _ = if CLI.flag "bundle" parsed then
    _ = hostBuild root env gfx;
    _ = K.copy "{root}/qos/{host}" "{destination}/{host}";
    invoke root env ["cc","-O2","-Wall","-Wextra","-DBUNDLE_HOST=\"{host}\"","-DBUNDLE_APP=\"{name}.qa\"","-DBUNDLE_DISK=\"{disk}\"","{root}/tools/bundle-runner.c","-o","{destination}/run"]
    else Unit;
  print "packed {destination}".
main : List String -> Unit .
main argv =
  parsed = K.need (CLI.parse options argv);
  operands = CLI.operands parsed;
  root = K.realpath (CLI.valueOr "." "root" parsed);
  _ = K.check "--root must name the QOS checkout" (K.isFile "{root}/tools/checkout-build.sol");
  configured = setting "FPRISC_ROOT" (if K.isFile "{root}/fprisc.path" then Str.trim (K.readText "{root}/fprisc.path") else if K.isFile "{root}/.installed" then "{root}/toolchain" else "{root}/../fprisc");
  fpr = K.realpath (CLI.valueOr configured "fprisc" parsed);
  env = [("FPRISC_ROOT",fpr),("FPR_HOME",root),("FPR_PATH",fpr),("FPR_FOREIGN","{root}/core/foreign.fpr")];
  runner = setting "SOL" "sol";
  cwd = K.trimEnd (K.command ["pwd","-P"]);
  workspace = setting "QOS_OUT" "{cwd}/.qos";
  _ = K.mkdirs workspace;
  if CLI.flag "help" parsed or operands == [] then
    print "usage: ./qbuild [--root QOS] [--fprisc FPRISC] build [fpr|host|native|all] | app SOURCE | plugin SOURCE | pack SOURCE [--out DIR] [--bundle] [--plugin SOURCE]"
  else case operands of
    ["build"] -> compilerBuild root env >> hostBuild root env False
  | ["build",what] ->
    _ = K.check "expected fpr, host, native or all" (List.has what ["fpr","host","native","all"]);
    _ = compilerBuild root env;
    _ = if what == "host" or what == "all" then hostBuild root env False else Unit;
    if what == "native" or what == "all" then invoke "{root}/qos" env ["make","-s","native","KERNEL={workspace}/qos-native.elf"] else Unit
  | ["app",source] ->
    item = project source; out = CLI.valueOr "{workspace}/{stem item.source}.qa" "out" parsed;
    buildDir = "{workspace}/build"; _ = K.mkdirs buildDir;
    invoke root env ([runner,"{root}/tools/build-checkout-app.sol","app",item.source,out,buildDir,CLI.valueOr "" "harts" parsed]+item.assignments)
  | ["plugin",source] ->
    out = CLI.valueOr "{workspace}/{stem source}.qa" "out" parsed;
    invoke root env ["make","-s","plugin-qa","PROG={K.realpath source}","PLUG_OUT={out}","BUILD={workspace}/build"]
  | ["profile"] -> invoke root env [runner,"{root}/tools/main-profile.sol","--root",root,"--fprisc",fpr,"--output",CLI.valueOr "{root}/build/profiles/Main" "out" parsed]
  | ["pack",source] -> package root env runner parsed source workspace
  | _ -> error "unknown build command or operands; use --help".
