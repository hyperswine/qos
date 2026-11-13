# Generate process and plugin manifests from the public ABI and compiler sidecar.
major header =
  definitions = List.map Str.words (Str.lines (readPath header));
  case List.filter (fn words -> case words of "#define" :: "QOS_ABI_VERSION" :: _ -> True | _ -> False) definitions of
    ["#define" :: "QOS_ABI_VERSION" :: raw :: _] ->
      digits = (if Str.endsWith "u" raw then substr raw 0 (Str.len raw - 1) else raw);
      if and (digits != "") (List.all (fn c -> and (c >= 48) (c <= 57)) (Str.codes digits)) then digits
      else error "invalid QOS_ABI_VERSION in {header}"
  | _ -> error "missing or ambiguous QOS_ABI_VERSION in {header}".
revision policy sidecar =
  if policy == "required" then Str.trim (readPath sidecar) else
    ProcessResult status _ _ = unwrap (Proc.runNow (ProcessSpec ["test","-e",sidecar] "" [] "" 0));
    case status of 0 -> Str.trim (readPath sidecar) | 1 -> "0" | _ -> error "cannot check {sidecar}".
generate mode entry header sidecar policy dest id name version =
  abi = major header; rev = revision policy sidecar;
  writePath dest "name = \"{name}\"\nid = \"{id}\"\nentry = \"{entry}\"\nversion = \"{version}\"\nloadMode = \"{mode}\"\nabi = \"{abi}.{rev}\"\n".
> case args Unit of
    [header,sidecar,policy,dest,id,name,version] -> generate "process" "n/a" header sidecar policy dest id name version
  | ["plugin",header,sidecar,dest,id] -> generate "plugin" "fpr_modtab" header sidecar "optional" dest id id "1"
  | _ -> error "usage: app-manifest.sol HEADER REVISION optional|required OUT ID NAME VERSION".
