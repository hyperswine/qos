# Store Python modules under their import names, preserving pathlib's component ordering.
Sort = use "../sdk/sort".
excluded = ["test","tests","idlelib","tkinter","turtledemo","ensurepip","venv","site-packages","dist-packages","__pycache__"].
key path = Str.join (Str.fromCode 0) (Str.split 47 path).
addBatches : unsafe String -> String -> List String -> Unit .
addBatches root archive paths = case paths of
    [] -> Unit
  | _ -> argv = List.append ["zip","-q","-9","-nw",archive,"--"] (List.take 100 paths);
    case Proc.streamNow (ProcessSpec argv root [] "" 0) of
      Ok 0 -> addBatches root archive (List.drop 100 paths)
    | failed -> error "building Python library archive failed: {failed}".
pack : unsafe String -> String -> Unit .
pack root archive =
  prune = List.concat (List.map (fn name -> ["-name",name,"-o"]) excluded);
  argv = List.concat [["find",".","(","-type","d","("],List.take (List.len prune - 1) prune,[")",")","-prune","-o","-name","*.py","-print0"]];
  ProcessResult code out err = unwrap (Proc.runNow (ProcessSpec argv root [] "" 0));
  if code != 0 then error "listing Python modules failed: {err}" else
    paths = Sort.sortBy key (List.filter (fn path -> path != "") (Str.split 0 out));
    if paths == [] then error "Python standard library contains no modules" else addBatches root archive paths.
main : unsafe Unit -> Unit .
> case args Unit of [root,archive] -> pack root archive | _ -> error "expected STDLIB NEW_ABSOLUTE_ARCHIVE".
