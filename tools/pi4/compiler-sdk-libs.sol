# Walk the ldd closure of the staged executables and Python extension modules.
S = use "../sdk/sort".
systemLibrary name =
  bases = ["libc.so","libm.so","libpthread.so","libdl.so","librt.so","libresolv.so","libutil.so"];
  Str.startsWith "ld-linux" name or List.any (fn base -> name == base or Str.startsWith (base + ".") name) bases.
dependency dest state line =
  (seen,pending) = state;
  case Str.words line of
    name :: "=>" :: path :: _ ->
      if Str.startsWith "/" path then
        if systemLibrary name or List.any (fn prior -> prior == name) seen then state else
          target = "{dest}/{name}";
          _ = (case Proc.streamNow (ProcessSpec ["cp","-pL",path,target] "" [] "" 0) of
              Ok 0 -> Unit | failed -> error "copy {name} failed: {failed}");
          (name :: seen,target :: pending)
      else if Str.contains "not found" line then error "unresolved SDK library: {line}" else state
  | _ -> if Str.contains "not found" line then error "unresolved SDK library: {line}" else state.
walkLibraries : unsafe String -> List String -> List String -> Unit .
walkLibraries dest seen paths = case paths of
    [] -> Unit
  | path :: rest ->
      ProcessResult code out err = unwrap (Proc.runNow (ProcessSpec ["ldd",path] "" [] "" 0));
      if code != 0 then error "ldd failed for {path}: {err}" else
        (next,pending) = List.fold (dependency dest) (seen,rest) (Str.lines out);
        walkLibraries dest next pending.
# Use the filename before the first dot, including for ABI-tagged modules.
includeModule path =
  excluded = ["_tkinter","_ssl","_hashlib","_ctypes","_curses","_curses_panel","_sqlite3","_dbm","_gdbm","_bz2","_lzma","_decimal","_asyncio","readline"];
  case Str.split 46 (List.last (Str.split 47 path)) of
    name :: _ -> not (List.any (fn excludedName -> excludedName == name) excluded)
  | _ -> False.
stageModules : unsafe String -> String -> List String .
stageModules source target =
  ProcessResult code out err = unwrap (Proc.runNow (ProcessSpec ["find",source,"-mindepth","1","-maxdepth","1","-name","*.so","-print0"] "" [] "" 0));
  if code != 0 then error "listing Python extensions failed: {err}" else
    paths = S.sortText (List.filter includeModule (List.filter (fn path -> path != "") (Str.split 0 out)));
    case paths of [] -> []
    | _ ->
      _ = unwrap (Proc.streamNow (ProcessSpec ["mkdir","-p",target] "" [] "" 0));
      argv = List.concat [["cp","-pL"],paths,[target + "/"]];
      case Proc.streamNow (ProcessSpec argv "" [] "" 0) of
        Ok 0 -> List.map (fn path -> target + "/" + List.last (Str.split 47 path)) paths
      | failed -> error "staging Python extensions failed: {failed}".
main : unsafe Unit -> Unit .
> case args Unit of dest :: source :: target :: roots ->
    extensions = if source == "" then [] else stageModules source target;
    walkLibraries dest [] (List.rev (List.append roots extensions))
  | _ -> error "expected LIB_DIRECTORY EXTENSION_SOURCE EXTENSION_TARGET ELF_ROOTS...".
