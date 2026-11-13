K = use "sdk/sdk".
splitArgs : unsafe List String -> List String -> (List String,List String) .
splitArgs argv flags = case argv of
    "--" :: sources -> (List.rev flags,sources)
  | flag :: rest -> splitArgs rest (flag :: flags)
  | [] -> error "expected -- before sources".
start prefix cc source =
  spec = ProcessSpec (prefix + [source] + cc) "" [] "" 0;
  K.need (Proc.start (PipelineSpec [spec] (PipeBytes (Bytes.empty Unit)) (PipeCapture 65536) PipeOutputInherit 0 PipeFail)).
finish job = case K.need (Proc.wait job) of
    PipelineResult 0 _ out _ -> Str.trim (unwrap (Utf8.decode out))
  | PipelineResult code _ _ _ -> error "object worker exited {code}".
compile : unsafe List String -> List String -> List String -> List String .
compile prefix cc sources = case sources of
    [] -> []
  | _ -> jobs = List.map (start prefix cc) (List.take 8 sources);
         objects = List.map finish jobs;
         objects + compile prefix cc (List.drop 8 sources).
build : unsafe String -> String -> List String -> Unit .
build worker cache argv =
  (cc,sources) = splitArgs argv [];
  driver = (case cc of first :: _ -> first | [] -> error "expected compiler");
  sol = (case unwrap (Env.get "SOL") of EnvText value -> value | EnvMissing -> "sol");
  _ = K.mkdirs cache; scratch = tempDir "ccobj-version"; version = "{scratch}/version";
  spec = ProcessSpec [driver,"--version"] "" [] "" 0;
  job = K.need (Proc.start (PipelineSpec [spec] (PipeBytes (Bytes.empty Unit)) (PipeFileNew version) PipeOutputInherit 0 PipeFail));
  _ = finish job;
  print (Str.join " " (compile [sol,worker,cache,version] cc sources)).
main : unsafe Unit -> Unit .
> case args Unit of worker :: cache :: rest -> build worker cache rest | _ -> error "expected WORKER CACHE CC FLAGS... -- SOURCE...".
