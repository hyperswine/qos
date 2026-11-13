# Stage the build recipes and tools needed to compile plugins on the Pi.
command argv = case Proc.streamNow (ProcessSpec argv "" [] "" 0) of
    Ok 0 -> Unit
  | result -> error "SDK input staging failed: {argv}: {result}".
stageFiles source target dir names =
  _ = command ["mkdir","-p","{target}/{dir}"];
  paths = List.map (fn name -> "{source}/{dir}/{name}") names;
  command (List.concat [["cp","-pL"],paths,["{target}/{dir}/"]]).
pathTest flag path = ProcessResult code _ _ = unwrap (Proc.runNow (ProcessSpec ["test",flag,path] "" [] "" 0)); code == 0.
# Find regular files and links to regular files without walking linked directories.
# Pass the NUL-delimited selection to tar and dereference file links on copy.
sources source target dir patterns =
  root = "{source}/{dir}";
  if not (pathTest "-d" root) then Unit else
    findArgs = List.concat [["find",".","(","-type","f","-o","(","-type","l","-exec","test","-f","\{}",";",")",")","("],patterns,[")","!","-name",".fpr","!","-name",".txt","-print0"]];
    ProcessResult code paths err = unwrap (Proc.runNow (ProcessSpec findArgs root [] "" 0));
    if code != 0 then error "source selection failed: {err}" else
    if paths == "" then Unit else
      dest = "{target}/{dir}";
      _ = command ["mkdir","-p",dest];
      env = [("COPYFILE_DISABLE","1")];
      pack = ProcessSpec ["tar","-chf","-","--null","-T","-"] root env "" 0;
      unpack = ProcessSpec ["tar","-xpf","-"] dest env "" 0;
      case Proc.pipeline (PipelineSpec [pack,unpack] (PipeBytes (unwrap (Utf8.encode paths))) PipeDiscard PipeOutputInherit 0 PipeFail) of
        Ok (PipelineResult 0 _ _ _) -> Unit
      | failed -> error "source staging failed: {failed}".
sourceTree source target dirs =
  _ = List.map (fn dir -> sources source target dir ["-name","*.fpr","-o","-name","*.txt"]) dirs;
  _ = (if pathTest "-f" "{source}/.fpr/versions.db" then stageFiles source target ".fpr" ["versions.db"] else Unit);
  sources source target ".fpr/store" ["-name","*.fpr"].
stage qos fpr sdk kind py =
  _ = sourceTree qos "{sdk}/qos" ["core","std","programs/mods"];
  _ = sourceTree fpr "{sdk}/fprisc" ["core","std"];
  _ = sources fpr "{sdk}/fprisc" "sol/lib" ["-name","*.sol"];
  _ = stageFiles qos "{sdk}/qos" "." ["Makefile","dependency.mk","qos-app.mk"];
  _ = command ["touch","{sdk}/qos/.installed"];
  _ = command ["ln","-s","../fprisc","{sdk}/qos/toolchain"];
  _ = stageFiles qos "{sdk}/qos" "qos/appside" ["qos_abi.h","link-qosplug.ld"];
  _ = stageFiles qos "{sdk}/qos" "hal/virt" ["qos-virt.mk"];
  _ = stageFiles qos "{sdk}/qos" "tools" ["qa-pack.sol","elf-image.sol","qa-relocations.sol","qa-moved.sol","qa-imports.sol","mkimports.sol","elf-symbols.sol","app-manifest.sol"];
  _ = stageFiles qos "{sdk}/qos" "tools/sdk" ["sort.sol"];
  _ = stageFiles fpr "{sdk}/fprisc" "compiler" ["Main.hs","Codegen.hs"];
  _ = command ["cp","-pL","{qos}/tools/pi4/compiler-sdk-run.sol","{sdk}/run.sol"];
  case kind of "editor" -> stageFiles qos "{sdk}/qos" "tools/pi4" ["EditorCompiler.hs"]
  | "full" -> Unit | _ -> error "unknown compiler kind {kind}".
probe sdk manifest =
  _ = command ["{sdk}/bin/sol","{sdk}/qos/tools/app-manifest.sol","plugin",
               "{sdk}/qos/qos/appside/qos_abi.h","{sdk}/missing.abirev",manifest,"probe"];
  lines = Str.lines (readPath manifest);
  if List.any (fn line -> line == "entry = \"fpr_modtab\"") lines then Unit
  else error "bundled Sol failed to generate a plugin manifest".
> case args Unit of [qos,fpr,sdk,kind,manifest,py] ->
    _ = stage qos fpr sdk kind py;
    probe sdk manifest
  | _ -> error "expected QOS FPRISC SDK COMPILER_KIND PROBE_MANIFEST".
