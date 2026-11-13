# Build the archive beside its destination so a failed size check preserves
# the previously published SDK. The caller owns the temporary directory.
J = use "sol/lib/json".
query argv =
  ProcessResult code out err = unwrap (Proc.runNow (ProcessSpec argv "" [] "" 0));
  if code == 0 then Str.trim out else error "{argv}: {err}".
pack sdk output scratch limit =
  temporary = "{scratch}/archive";
  env = [("COPYFILE_DISABLE","1")];
  tar = ProcessSpec ["tar","-cf","-","-C",sdk,"."] "" env "" 0;
  gzip = ProcessSpec ["gzip","-9","-c"] "" [] "" 0;
  _ = (case Proc.pipeline (PipelineSpec [tar,gzip] (PipeBytes (Bytes.empty Unit)) (PipePublish temporary False) PipeOutputInherit 0 PipeFail) of
      Ok (PipelineResult 0 _ _ _) -> Unit
    | result -> error "SDK archive failed: {result}");
  statArgs = if query ["uname","-s"] == "Darwin" then ["stat","-f","%z"] else ["stat","-c","%s"];
  size = parseInt (query (List.append statArgs [temporary]));
  _ = (if size > limit * 1048576 then error "SDK exceeds {limit} MiB compressed: {size}" else Unit);
  sizes = query (List.concat [["find",sdk,"-type","f","-exec"],statArgs,["\{}","+"]]);
  expanded = List.fold (fn total n -> total + parseInt n) 0 (List.filter (fn line -> line != "") (Str.lines sizes));
  reader = unwrap (Stream.openRead temporary 65536);
  (result,done) = Sha256.stream reader;
  _ = unwrap (Stream.closeRead done);
  digest = Hex.encode (unwrap result);
  _ = query ["mv","-f",temporary,output];
  name = case List.rev (Str.split 47 output) of head :: _ -> head | _ -> error "missing archive name";
  _ = writePath "{output}.sha256" "{digest}  {name}\n";
  print (J.render (J.JObj [("archive",J.JStr output),("compressed_bytes",J.JNum size),
                          ("expanded_bytes",J.JNum expanded),("sha256",J.JStr digest)])).
> case args Unit of [sdk,output,scratch,limit] -> pack sdk output scratch (parseInt limit)
  | _ -> error "expected SDK OUTPUT SCRATCH MAX_COMPRESSED_MIB".
