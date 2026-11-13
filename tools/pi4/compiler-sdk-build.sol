J = use "sol/lib/json".
query argv =
  ProcessResult code out err = unwrap (Proc.runNow (ProcessSpec argv "" [] "" 0));
  if code == 0 then Str.trim out else error "SDK command failed: {argv}: {err}".
invoke argv = case Proc.streamNow (ProcessSpec argv "" [] "" 0) of
    Ok 0 -> Unit | failed -> error "SDK command failed: {argv}: {failed}".
strings text = List.map (fn value -> unwrap (J.text value)) (unwrap (J.parse text |>? J.items)).
revision value = case value of
    J.JArr [J.JStr commit,dirty] -> (commit,J.render dirty)
  | _ -> error "invalid SDK revision result".
build qos fpr compiler sol kind qr fr work output scratch limit python py stdlib extensions arch glibc bootstrap =
  sdk = "{work}/sdk";
  tools = "{qos}/tools/pi4";
  roots = strings (query (List.concat [bootstrap,["{tools}/compiler-sdk-tools.sol",sdk,compiler,sol,python]]));
  child name argv = List.append ["{sdk}/bin/sol","{tools}/compiler-sdk-{name}.sol"] argv;
  provenance = unwrap (J.parse (query (child "revisions" [qos,qr,fpr,fr])) |>? J.items);
  case provenance of
    [q,f] ->
      (qRev,qDirty) = revision q;
      (fRev,fDirty) = revision f;
      _ = invoke (child "inputs" [qos,fpr,sdk,kind,"{work}/probe.toml"]);
      _ = invoke ["install","-m","755","{tools}/qos-fprd","{sdk}/bin/qos-fprd"];
      invoke (child "package" (List.append [tools,sdk,compiler,arch,py,kind,glibc,qRev,fRev,qDirty,fDirty,stdlib,extensions,output,scratch,limit] roots))
  | _ -> error "expected revisions for both SDK source trees".
> case args Unit of qos :: fpr :: compiler :: sol :: kind :: qr :: fr :: work :: output :: scratch :: limit :: python :: py :: stdlib :: extensions :: arch :: glibc :: bootstrap ->
    build qos fpr compiler sol kind qr fr work output scratch limit python py stdlib extensions arch glibc bootstrap
  | _ -> error "expected compiler SDK build parameters".
