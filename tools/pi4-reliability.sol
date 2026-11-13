M = use "pi4-bundle-manifest".
J = use "sol/lib/json".
P = use "pi4/build-programs".
K = use "sdk/sdk".
inbox fpr out cc name =
  extra = (if name == "inboxownership" then ["--with","{fpr}/tests/base/inbox_probe.c"] else []);
  P.command fpr (["{fpr}/fpr","build","{fpr}/tests/base/{name}.fpr","--harts","4","--cc",cc,"-o","{out}/{name}-base"] + extra).
plugin qos out source =
  base = K.baseName source; suffix = K.suffix base;
  name = Str.slice base 0 (Str.len base - Str.len suffix);
  _ = P.archiveSource qos out "plugin-qa-a64" "PLUG_OUT" source name;
  "{out}/{name}.qa".
buildReliability qos fpr out cc apps =
  _ = P.command fpr ["make","-s","fpr"];
  _ = List.map (inbox fpr out cc) ["inbox","inboxshared","inboxownership"];
  installed = List.map (plugin qos out) apps;
  _ = List.map (plugin qos out) ["tests/mathv1.fpr","tests/mathv2.fpr"];
  _ = P.archiveSource qos out "qos-app-a64" "QA_OUT" "tests/mainreliability.fpr" "main";
  _ = List.map (P.archive qos out "qos-app-a64" "QA_OUT") ["storagedeadlines","storagebudgets","blockmemory","filesshutdown","filessvc"];
  _ = P.eglHost qos "qos" out cc;
  _ = P.runner qos qos out cc;
  sol = (case unwrap (Env.get "SOL") of EnvText path -> path | EnvMissing -> "sol");
  P.command qos ([sol,"{qos}/tools/mkdisk.sol","--record","soak/reload-a","{out}/mathv1.qa","--record","soak/reload-b","{out}/mathv2.qa","{out}/Main.disk","32"] + installed).
bundle : unsafe String -> String -> String -> List String -> Unit .
bundle qos output cc apps =
  fpr = (case unwrap (Env.get "FPRISC_ROOT") of EnvText path -> K.realpath path | EnvMissing -> K.realpath "{qos}/../fprisc");
  _ = K.mkdirs (K.parent output);
  _ = P.command "" ["mkdir",output];
  out = K.realpath output;
  _ = buildReliability qos fpr out cc apps;
  M.writeBundle qos fpr out [("cc",M.compilerVersion cc),
    ("scope",J.JStr "diagnostic Main entry; two reload generations; isolated SD-backed disk")].
main : unsafe Unit -> Unit .
> case args Unit of qos :: output :: cc :: apps -> bundle qos output cc apps
  | _ -> error "usage: pi4-reliability QOS OUTPUT CC [APP...]".
