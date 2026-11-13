# Build a checkout app using the host-specific image selected by qos-app.mk.
invoke directory argv =
  status = unwrap (Proc.streamNow (ProcessSpec argv directory [] "" 0));
  if status == 0 then Unit else Script.abort status.
build source archive directory harts manifest =
  workers = if harts == "" then [] else ["HARTS={harts}"];
  argv = List.concat [["make","-s","qos-app","PROG={source}","QA_OUT={archive}","BUILD={directory}"],manifest,workers];
  invoke "" argv.
plugins : unsafe String -> List String -> List String .
plugins directory pairs = case pairs of
    [] -> []
  | source :: archive :: rest ->
      _ = invoke "" ["make","-s","plugin-qa","PROG={source}","PLUG_OUT={archive}","BUILD={directory}"];
      archive :: plugins directory rest
  | _ -> error "expected source and archive for each plugin".
> case args Unit of "plugins" :: directory :: diskTool :: image :: size :: pairs ->
    archives = plugins directory pairs;
    runner = case unwrap (Env.get "SOL") of EnvText path -> path | EnvMissing -> "sol";
    invoke directory ([runner,diskTool,image,size] + archives)
  | "app" :: source :: archive :: directory :: harts :: manifest ->
    build source archive directory harts manifest
  | _ -> error "expected source, archive, build directory, hart count and optional manifest assignments".
