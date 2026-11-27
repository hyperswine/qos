# Walk the ldd closure of the staged executables and Python extension modules.
S = use "../sdk/sort".
systemLibrary name =
  bases = ["libc.so","libm.so","libpthread.so","libdl.so","librt.so","libresolv.so","libutil.so"];
  Str.startsWith "ld-linux" name or List.any (fn base -> name == base or Str.startsWith (base + ".") name) bases.
dependency dest state line =
  (seen,pending) = state;
  # ldd indents with a tab, which Str.words does not split on
  case Str.words (Str.replace (Str.fromCode 9) " " line) of
    name :: "=>" :: path :: _ ->
      if Str.startsWith "/" path then
        if systemLibrary name or List.any (fn prior -> prior == name) seen then state else
          target = "{dest}/{name}";
          _ = (case Proc.streamNow (ProcessSpec ["cp","-pL",path,target] "" [] "" 0) of
              Ok 0 -> Unit | failed -> error "copy {name} failed: {failed}");
          # a library's own dependencies do not use the executable's runpath:
          # each bundled library finds its siblings beside it (the Pi has no
          # libGLdispatch, which a bundled glvnd libEGL needs; 27 Nov 2026)
          _ = (case Proc.streamNow (ProcessSpec ["chmod","u+w",target] "" [] "" 0) of
              Ok 0 -> Unit | failed -> error "chmod {name} failed: {failed}");
          _ = (case Proc.streamNow (ProcessSpec ["patchelf","--set-rpath","$ORIGIN",target] "" [] "" 0) of
              Ok 0 -> Unit | failed -> error "patchelf --set-rpath on {name} failed (install patchelf in the builder): {failed}");
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
main : unsafe Unit -> Unit .
> case args Unit of dest :: roots ->
    walkLibraries dest [] (List.rev roots)
  | _ -> error "expected LIB_DIRECTORY ELF_ROOTS...".
