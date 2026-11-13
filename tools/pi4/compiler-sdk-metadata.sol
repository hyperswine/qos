S = use "../sdk/sort".
J = use "sol/lib/json".
D = use "sol/lib/digest".
selected path =
  name = List.last (Str.split 47 path);
  name == "Makefile" or List.any (fn ext -> name != ext and Str.endsWith ext name) [".sol",".py",".fpr",".hs",".h",".txt",".ld",".mk",".db"].
# pathlib orders components separately. NUL sorts before every filename byte.
componentKey path = Str.join (Str.fromCode 0) (Str.split 47 path).
files : unsafe String -> String -> List String .
files sdk tree =
  ProcessResult code names err = unwrap (Proc.runNow (ProcessSpec ["find",tree,"-type","f","-print0"] sdk [] "" 0));
  if code != 0 then error "finding SDK sources failed: {err}" else
    S.sortBy componentKey (List.filter selected (List.filter (fn path -> path != "") (Str.split 0 names))).
add bytes hash = unwrap (Sha256.update bytes hash).
source sdk hash path =
  prefix = unwrap (Utf8.encode (path + Str.fromCode 0));
  reader = unwrap (Stream.openRead "{sdk}/{path}" 65536);
  (result,next) = Stream.foldChunks (fn h bytes -> add bytes h) (add prefix hash) reader;
  _ = unwrap (Stream.closeRead next);
  add (unwrap (Bytes.fromList [0])) (unwrap result).
metadata : unsafe String -> String -> String -> String -> String -> String -> String -> String -> String -> String -> Unit .
metadata sdk compiler arch py kind glibc qr fr qd fd =
  paths = List.append (files sdk "qos") (files sdk "fprisc");
  fingerprint = Hex.encode (Sha256.finish (List.fold (source sdk) (Sha256.init Unit) paths));
  digest path = J.JStr (unwrap (D.sha256File path));
  entry = if kind == "editor" then digest "{sdk}/qos/tools/pi4/EditorCompiler.hs" else J.JNull;
  record = J.JObj [("format",J.JNum 1),("arch",J.JStr arch),("python",J.JStr py),("compiler_kind",J.JStr kind),
    ("entrypoint_sha256",entry),("glibc",J.JStr glibc),("qos_revision",J.JStr qr),("fprisc_revision",J.JStr fr),
    ("qos_dirty",unwrap (J.parse qd)),("fprisc_dirty",unwrap (J.parse fd)),("bundled_source_sha256",J.JStr fingerprint),
    ("compiler_input_sha256",digest compiler),("compiler_sha256",digest "{sdk}/fprisc/fpr")];
  writePath "{sdk}/sdk.json" (J.pretty record + "\n").
main : unsafe Unit -> Unit .
> case args Unit of [sdk,compiler,arch,py,kind,glibc,qr,fr,qd,fd] -> metadata sdk compiler arch py kind glibc qr fr qd fd
  | _ -> error "expected SDK COMPILER ARCH PYTHON KIND GLIBC QOS_REV FPR_REV QOS_DIRTY FPR_DIRTY".
