J = use "sol/lib/json".
command argv = case Proc.streamNow (ProcessSpec argv "" [] "" 0) of
    Ok 0 -> Unit | failed -> error "tool staging failed: {argv}: {failed}".
copyTool from dest =
  _ = command ["cp","-pL",from,dest]; dest.
resolve name =
  ProcessResult code out err = unwrap (Proc.runNow (ProcessSpec ["which",name] "" [] "" 0));
  if code == 0 then Str.trim out else error "missing SDK build tool {name}: {err}".
stage sdk compiler sol python =
  bin = "{sdk}/bin";
  _ = command ["mkdir","-p",bin,"{sdk}/lib","{sdk}/qos","{sdk}/fprisc"];
  roots = List.map (fn name -> copyTool (resolve name) "{bin}/{name}") ["make","gcc","as","ld"];
  ProcessResult code out err = unwrap (Proc.runNow (ProcessSpec ["gcc","-print-prog-name=collect2"] "" [] "" 0));
  _ = (if code == 0 then Unit else error "gcc collect2 lookup failed: {err}");
  collectPath = copyTool (Str.trim out) "{bin}/collect2";
  fpr = copyTool compiler "{sdk}/fprisc/fpr";
  _ = command ["ln","-s","fpr","{sdk}/fprisc/fprc"];
  solRoots = (if sol == "" then
      _ = command ["ln","-s","../fprisc/fpr","{bin}/sol"]; []
    else [copyTool sol "{bin}/sol"]);
  py = if python == "" then [] else
    _ = command ["mkdir","-p","{sdk}/python/lib"];
    [copyTool python "{bin}/python3"];
  print (J.render (J.JArr (List.map J.JStr (List.concat [roots,[collectPath,fpr],solRoots,py])))).
> case args Unit of [sdk,compiler,sol,python] -> stage sdk compiler sol python
  | _ -> error "expected SDK COMPILER SOL_OR_EMPTY PYTHON".
