# Run from the extracted SDK root. Native plugin build without a daemon.
need r = case r of Ok value -> value | Err why -> error "{why}".
check why ok = if ok then Unit else error why.
command argv = ProcessResult status out err = need (Proc.runNow (ProcessSpec argv "" [] "" 0));
  if status == 0 then Str.trim out else error "{argv}: {err}".
realpath path = command ["realpath",path].
parent path = command ["dirname",path].
baseName path = command ["basename",path].
isFile path = ProcessResult status _ _ = need (Proc.runNow (ProcessSpec ["test","-f",path] "" [] "" 0)); status == 0.
mkdirs path = _ = command ["mkdir","-p",path]; Unit.
cliMain argv =
  root = command ["pwd","-P"];
  _ = check "run from the extracted SDK root" (isFile "{root}/sdk.json");
  inheritedPath = case need (Env.get "PATH") of EnvText path -> path | EnvMissing -> "/usr/bin:/bin";
  env = [("PATH","{root}/bin:{inheritedPath}"),("GHCRTS","-M512m -K64m"),("FPRISC_ROOT","{root}/fprisc"),("FPR_HOME","{root}/qos"),("FPR_PATH","{root}/fprisc"),
    ("FPR_FOREIGN","{root}/qos/core/foreign.fpr"),("SOL","{root}/bin/sol"),
    ("COMPILER_PATH","{root}/bin"),("LC_ALL","C.UTF-8"),
    ("PLUG_A64_LINK","gcc -fno-use-linker-plugin -nostdlib -nostartfiles -static -no-pie -Wl,--build-id=none -Wl,-z,noexecstack -Wl,--no-relax -T $(QOS)/appside/link-qosplug.ld -Wl,--emit-relocs")];
  execute = fn argv ->
    status = need (Proc.streamNow (ProcessSpec argv "{root}/qos" env "" 0));
    if status == 0 then Unit else Script.abort status;
  case argv of
    ["check",source] -> execute ["{root}/fprisc/fpr","--target=qa64","--plugin","--check-only","--prelude={root}/fprisc/core/prelude.fpr",realpath source,"/dev/null"]
  | ["plugin",source,out,work] ->
    _ = mkdirs work;
    destination = realpath (parent out)+"/"+baseName out;
    execute ["make","plugin-qa-a64","PROG={realpath source}","PLUG_OUT={destination}","BUILD={realpath work}"]
  | _ -> error "usage: bin/sol run.sol check SOURCE | plugin SOURCE OUT WORK".
> cliMain (args Unit).
