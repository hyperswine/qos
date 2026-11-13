K = use "sdk/sdk".
J = use "sol/lib/json".
tree root scratch =
  head = K.revision root;
  _ = K.git root ["diff","--output={scratch}/changes","HEAD"];
  J.JObj [("head",J.JStr head),("tracked_diff_sha256",J.JStr (K.sha256 "{scratch}/changes"))].
writeBundle : unsafe String -> String -> String -> List (String, J.Json) -> Unit .
writeBundle qos fpr out metadata =
  scratch = tempDir "pi4-manifest";
  # The bundle inventory includes regular files and file symlinks at its root.
  listing = K.command ["/usr/bin/find","-L",out,"-mindepth","1","-maxdepth","1","-type","f","!","-name","manifest.json","-print0"];
  paths = K.sortText (List.filter (fn p -> p != "") (Str.split 0 listing));
  files = J.JObj (List.map (fn p -> (K.baseName p,J.JStr (K.sha256 (K.realpath p)))) paths);
  K.writeJson "{out}/manifest.json" (J.JObj ([("qos",tree qos scratch),("fprisc",tree fpr scratch),("files",files)] + metadata)).
compilerVersion cc = case Str.lines (K.command [cc,"--version"]) of first :: _ -> J.JStr first | [] -> error "missing compiler version".
manifest : unsafe String -> String -> String -> String -> Unit .
manifest qos fpr out cc = writeBundle qos fpr out [("cc",J.JStr cc),("cc_version",compilerVersion cc),("harts",J.JNum 4),
    ("fault_injection",J.JArr [J.JStr "QOS_BLK_TEST",J.JStr "QOS_STORE_TEST"])].
