# sdk.sol -- what the SDK stager and packager share (tools/stage-portable-sdk.sol,
# tools/package-portable-sdk.sol).
#
# Every file operation here is IMMEDIATE (streams, digest streams, and cp/ln/
# chmod/find/tar run as processes): the stager builds a tree and hashes it in
# one run, so it must not take transactional observations a later step of
# the same run would invalidate.
P = use "sol/lib/proc".
J = use "sol/lib/json".
D = use "sol/lib/digest".

need r = case r of Ok x -> x | Err why -> error "{why}".
check why yes = if yes then Unit else error why.

# a tool's stdout; its failure is the script's
command argv = need (P.output (Proc.runNow (P.withTimeout 1800000 (P.spec argv)))).
commandIn dir argv = need (P.output (Proc.runNow (P.withTimeout 1800000 (P.inDir dir (P.spec argv))))).
# Ok code, whatever it is
status argv = case Proc.runNow (P.withTimeout 1800000 (P.spec argv)) of
    Ok (ProcessResult code _ _) -> code
  | Err why -> error why.

trimEnd t = Str.trim t.
drop n t = Str.slice t n (Str.len t).

# merge sort by a String key (byte order, as Python sorts ASCII)
sortBy : unsafe (a -> String) -> List a -> List a .
sortBy key xs = case xs of
    [] -> []
  | [x] -> [x]
  | _ ->
      half = List.len xs / 2;
      merge key (sortBy key (List.take half xs)) (sortBy key (List.drop half xs)).
merge : unsafe (a -> String) -> List a -> List a -> List a .
merge key a b = case (a, b) of
    ([], _) -> b
  | (_, []) -> a
  | (x :: xs, y :: ys) -> (case strCmp (key x) (key y) <= 0 of
      True -> x :: merge key xs b
    | False -> y :: merge key a ys).
sortText : unsafe List String -> List String .
sortText xs = sortBy (fn x -> x) xs.
lines text = List.filter (fn s -> s != "") (Str.split 10 text).

exists path = status ["/bin/test", "-e", path] == 0.
isFile path = status ["/bin/test", "-f", path] == 0.
isLink path = status ["/bin/test", "-L", path] == 0.
realpath path = trimEnd (command ["/bin/realpath", path]).
mkdirs path = _ = command ["/bin/mkdir", "-p", path]; Unit.
# a copy that keeps the mode (shutil.copy2), following links
copy from to =
  _ = mkdirs (parent to);
  _ = command ["/bin/cp", "-pL", from, to];
  Unit.
copyTree from to = _ = command ["/bin/cp", "-pPR", from, to]; Unit.
symlink target name = _ = command ["/bin/ln", "-s", target, name]; Unit.
writable tree = _ = command ["/bin/chmod", "-R", "u+w", tree]; Unit.

parent p = case Str.split 47 p of
    [] -> "."
  | parts -> (case List.len parts <= 1 of
      True -> "."
    | False -> Str.join "/" (List.take (List.len parts - 1) parts)).
baseName p = case List.rev (Str.split 47 p) of x :: _ -> x | [] -> p.
suffix p =
  b = baseName p;
  case List.rev (Str.split 46 b) of
    x :: _ :: _ -> (case Str.startsWith "." b and List.len (Str.split 46 b) == 2 of True -> "" | False -> ".{x}")
  | _ -> "".

# the regular files under dir, relative and sorted (links are not followed)
files : unsafe String -> List String .
files dir = sortText (List.map (fn p -> drop (Str.len dir + 1) p) (lines (command ["/usr/bin/find", dir, "-type", "f"]))).

sha256 path = need (D.sha256File path).
sha256Text text = Hex.encode (Sha256.bytes (need (Utf8.encode text))).

readText path =
  r = need (Stream.openRead path 65536);
  (result, r2) = Stream.foldChunks (fn acc b -> b :: acc) [] r;
  _ = need (Stream.closeRead r2);
  need (Utf8.decode (Bytes.concat (List.rev (need result)))).

# written now: bytes to private scratch, then published in place
writeText path text =
  scratch = tempDir "sdk-write";
  w = need (Stream.openWrite "{scratch}/bytes" 16777216);
  (result, w2) = Stream.writeChunk (need (Utf8.encode text)) w;
  _ = need (Stream.closeWrite w2);
  _ = need result;
  _ = need (Fs.copyPublishNow "{scratch}/bytes" path 65536 True);
  Unit.

writeJson path value = writeText path "{J.pretty value}\n".

# { relative path: sha256 } of every file under root, except the inventory itself
inventory : unsafe String -> J.Json .
inventory root = J.JObj (List.map (fn name -> (name, J.JStr (sha256 "{root}/{name}")))
  (List.filter (fn name -> baseName name != "files.sha256.json") (files root))).

# One hash over the platform inventory, as qos build computes it:
# sha256 of the sorted lines "SHA  NAME\n".
platformDigest : unsafe List (String, String) -> String .
platformDigest pairs = sha256Text (Str.join "" (List.map (fn p -> (name, sha) = p; "{sha}  {name}\n") (sortBy (fn p -> (name, _) = p; name) pairs))).

field key value = need (J.get key value).
text key value = need (J.text (field key value)).
textOr d key value = case J.get key value of Ok (J.JStr t) -> t | _ -> d.
has key value = case J.get key value of Ok _ -> True | Err _ -> False.
truthy key value = case J.get key value of
    Ok (J.JBool b) -> b
  | Ok (J.JObj (_ :: _)) -> True
  | Ok (J.JArr (_ :: _)) -> True
  | Ok (J.JStr t) -> t != ""
  | Ok (J.JNum n) -> n != 0
  | _ -> False.

git tree argv = command (["/usr/bin/git", "-C", tree] + argv).
revision tree = trimEnd (git tree ["rev-parse", "HEAD"]).
dirty tree = trimEnd (git tree ["status", "--porcelain"]) != "".

# the leading decimal digits of a word ("22u /* ... */" -> "22")
digitsOf : unsafe String -> String .
digitsOf t = Str.slice t 0 (digitsEnd t 0).
digitsEnd : unsafe String -> Int -> Int .
digitsEnd t i = if i < Str.len t and Str.at t i >= 48 and Str.at t i <= 57 then digitsEnd t (i + 1) else i.

# the number after `#define NAME` in a C header
defineOf : unsafe String -> String -> String .
defineOf name text = case List.filter (fn l -> Str.startsWith "#define {name} " l or Str.startsWith "#define {name}\t" l) (lines text) of
    l :: _ -> digitsOf (Str.trim (drop (Str.len "#define {name}") l))
  | [] -> error "no #define {name}".
# the number in `NAME = N` at the start of a line (Codegen.hs codegenRev)
bindingOf : unsafe String -> String -> String .
bindingOf name text = case List.filter (fn l -> Str.startsWith "{name} = " l) (lines text) of
    l :: _ -> digitsOf (Str.trim (drop (Str.len "{name} = ") l))
  | [] -> error "no {name} binding".
