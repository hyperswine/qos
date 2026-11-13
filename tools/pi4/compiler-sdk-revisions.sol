# Record both trees before staging. A source export has unknown dirty status.
J = use "sol/lib/json".
git tree args = unwrap (Proc.runNow (ProcessSpec (List.append ["git","-C",tree] args) "" [] "" 0)).
revision tree explicit =
  ProcessResult status head err = git tree ["rev-parse","HEAD"];
  if status != 0 then
    if explicit == "" then error "source export {tree} needs an explicit revision argument" else
      J.JArr [J.JStr explicit,J.JNull]
  else
    actual = Str.trim head;
    if and (explicit != "") (explicit != actual) then error "source revision mismatch: {actual} != {explicit}" else
      ProcessResult code changes why = git tree ["status","--porcelain"];
      if code != 0 then error "cannot determine dirty status of {tree}: {why}" else
        J.JArr [J.JStr actual,J.JBool (changes != "")].
> case args Unit of [qos,qosRevision,fpr,fprRevision] ->
    print (J.render (J.JArr [revision qos qosRevision,revision fpr fprRevision]))
  | _ -> error "expected QOS QOS_REVISION FPRISC FPRISC_REVISION".
