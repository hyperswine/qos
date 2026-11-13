K = use "sdk/sdk".
Programs = use "pi4/build-programs".
Manifest = use "pi4-bundle-manifest".
envOr name fallback = case unwrap (Env.get name) of EnvText v -> if v == "" then fallback else v | EnvMissing -> fallback.
buildBundle : unsafe String -> String -> Unit .
buildBundle qos output =
  fpr = K.realpath (envOr "FPRISC_ROOT" "{qos}/../fprisc");
  home = envOr "HOME" ""; cc = envOr "TARGET_CC" "{home}/.cache/qosp-br/rpi4/host/bin/aarch64-buildroot-linux-gnu-gcc";
  path = (if output == "" then "{qos}/.qos/pi4/validation/bundle" else output);
  _ = K.mkdirs path; out = K.realpath path;
  _ = Programs.compileBundle qos fpr out cc;
  _ = Manifest.manifest qos fpr out cc;
  print "BUNDLE COMPLETE".
> case args Unit of qos :: rest -> (case rest of out :: _ -> buildBundle qos out | [] -> buildBundle qos "")
  | _ -> error "usage: build.sh [OUTPUT]".
