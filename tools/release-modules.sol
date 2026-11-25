# Commit every library module release.toml lists under `modules`, so each pin
# in the tree names a committed version (release.toml, docs/2026-11-25-FPR-COMMIT-CLEAN.md).
#   sol tools/release-modules.sol check    commit each one in a throwaway copy of the
#                                          tree; fail if fpr refuses any (CI runs this)
#   sol tools/release-modules.sol commit   commit each one here, in release.toml order
# A refusal names its fix: `fpr pin <module> --deps` writes missing pins, and a
# signature break is minted by hand with `fpr commit <module> --major`.
# FPRISC_ROOT names the compiler checkout (default ../fprisc), as in CI.
B = use "sol/lib/build".
quoted line = case Str.split 34 line of _ :: name :: _ -> [name] | _ -> [].
listed : unsafe List String -> List String .
listed lines = case lines of
    [] -> []
  | line :: rest -> if Str.startsWith "]" line then [] else List.append (quoted line) (listed rest).
section : unsafe List String -> List String .
section lines = case lines of
    [] -> []
  | line :: rest -> if Str.startsWith "modules" line then listed rest else section rest.
modules : unsafe String -> List String .
modules root = section (List.map Str.trim (Str.lines (readPath "{root}/release.toml"))).
fprEnv root fpr = [("FPRISC_ROOT",fpr),("FPR_HOME",root),("FPR_PATH","{root}/programs:{fpr}"),("FPR_FOREIGN","{root}/core/foreign.fpr")].
# One module: Ok summary line, or Err with fpr's own refusal text.
commitOne root fpr m =
  ProcessResult code out err = unwrap (Proc.runNow (ProcessSpec ["{fpr}/fpr","commit",m] root (fprEnv root fpr) "" 600000));
  outcome = List.filter (fn l -> Str.contains "committed " l or Str.contains "no-op" l) (Str.lines out);
  if code == 0 then Ok (case List.rev outcome of l :: _ -> l | [] -> "committed")
  else Err (Str.join "\n" (List.filter (fn l -> not (Str.contains "resolved from .fpr store" l)) (List.append (Str.lines out) (Str.lines err)))).
reportOne pair = (m, r) = pair; case r of
    Ok line -> print "ok   {m}: {line}"
  | Err why -> print "FAIL {m}:\n{why}".
refused pair = (m, r) = pair; case r of Ok _ -> False | Err _ -> True.
commitAll : List String -> String -> String -> Int .
commitAll mods root fpr =
  _ = (if mods == [] then error "release.toml lists no modules" else Unit);
  results = List.map (fn m -> (m, commitOne root fpr m)) mods;
  _ = List.map reportOne results;
  bad = List.filter refused results;
  _ = print "release modules: {List.len mods} listed, {List.len bad} refused";
  List.len bad.
main : unsafe List String -> Unit .
main argv =
  root = B.query ["pwd","-P"];
  # read release.toml before any copy: the listing always comes from this tree
  mods = modules root;
  fpr = B.query ["realpath",B.setting "FPRISC_ROOT" "{root}/../fprisc"];
  case argv of
    ["commit"] -> if commitAll mods root fpr == 0 then Unit else Script.exit 1
  | ["check"] ->
      scratch = B.query ["mktemp","-d"];
      _ = B.command ["cp","-a","{root}/.","{scratch}/tree"];
      bad = commitAll mods "{scratch}/tree" fpr;
      _ = B.command ["rm","-rf",scratch];
      if bad == 0 then Unit else Script.exit 1
  | _ -> error "usage: sol tools/release-modules.sol check|commit".
> main (args Unit).
