CLI = use "sol/lib/cli".
J = use "sol/lib/json".
options = List.map (fn name -> CLI.Option name "" CLI.One)
  ["qos","fprisc","compiler","compiler-kind","sol","qos-revision","fprisc-revision","output","max-compressed-mib","python-runtime"].
query argv =
  ProcessResult status out err = unwrap (Proc.runNow (ProcessSpec argv "" [] "" 0));
  if status == 0 then Str.trim out else error "command failed: {argv}: {err}".
required parsed key = value = CLI.valueOr "" key parsed;
  if value == "" then error "missing --{key}" else value.
# Optional legacy compiler daemon: copy an explicit target Python runtime.
# The build never executes it. The default SDK has no Python dependency.
pythonRuntime prefix = if prefix == "" then ["","","",""] else
  executable = query ["realpath","{prefix}/bin/python3"];
  name = query ["basename",executable];
  version = substr name 6 (Str.len name - 6);
  _ = if Str.startsWith "python3." name then Unit else error "python-runtime/bin/python3 must resolve to python3.MINOR";
  stdlib = "{prefix}/lib/python{version}";
  [executable,version,stdlib,"{stdlib}/lib-dynload"].
package parsed =
  opt name fallback = CLI.valueOr fallback name parsed;
  arch = query ["uname","-m"];
  _ = (if and (query ["uname","-s"] == "Linux") (List.has arch ["arm64","aarch64"]) then Unit else error "build on native AArch64 Linux");
  fpr = query ["realpath",required parsed "fprisc"];
  qos = query ["realpath",opt "qos" "."];
  compiler = query ["realpath",required parsed "compiler"];
  output = query ["realpath","-m",required parsed "output"];
  kind = opt "compiler-kind" "full";
  _ = (if List.has kind ["full","editor"] then Unit else error "expected full or editor compiler");
  provided = opt "sol" "";
  separate = if provided != "" then query ["realpath",provided] else if kind == "editor" then query ["which","sol"] else "";
  # Preserve the sol argv[0] name when bootstrapping a multi-call compiler.
  bootstrap = if provided != "" then [provided] else if separate != "" then [separate] else [compiler,"sol"];
  py = pythonRuntime (opt "python-runtime" "");
  glibc = query ["getconf","GNU_LIBC_VERSION"];
  limit = opt "max-compressed-mib" "40";
  _ = parseInt limit;
  parent = query ["dirname",output];
  _ = query ["mkdir","-p",parent];
  work = query ["mktemp","-d","{parent}/.qos-sdk-XXXXXXXX"];
  env = [("FPR_HOME",fpr),("XDG_STATE_HOME","{work}/state"),("XDG_CACHE_HOME","{work}/cache")];
  argv = List.concat [bootstrap,["{qos}/tools/pi4/compiler-sdk-build.sol",qos,fpr,compiler,separate,kind,
    opt "qos-revision" "",opt "fprisc-revision" "",work,output,work,limit],py,[arch,glibc],bootstrap];
  result = Proc.streamNow (ProcessSpec argv "" env "" 0);
  _ = query ["rm","-rf",work];
  case result of Ok 0 -> Unit | failed -> error "SDK build failed: {failed}".
> parsed = unwrap (CLI.parse options (args Unit));
  if CLI.operands parsed != [] then error "unexpected positional arguments" else package parsed.
