# Compile or reuse one object. A batch shares the captured compiler version.
K = use "sdk/sdk".
digest path = unwrap (Hex.decode (K.sha256 path)).
objectKey version cc seen =
  nul = unwrap (Utf8.decode (unwrap (Bytes.fromList [0])));
  flags = Sha256.bytes (unwrap (Utf8.encode (Str.join nul cc)));
  key = Sha256.bytes (Bytes.concat [digest version,flags,digest seen]);
  substr (Hex.encode key) 0 32.
runCompiler argv =
  spec = ProcessSpec argv "" [] "" 0;
  job = K.need (Proc.start (PipelineSpec [spec] (PipeBytes (Bytes.empty Unit)) PipeDiscard PipeOutputInherit 0 PipeFail));
  case K.need (Proc.wait job) of
    PipelineResult 0 _ _ _ -> Unit
  | PipelineResult code _ _ _ -> error "compiler exited {code}: {argv}".
build cache version source cc =
  scratch = tempDir "ccobj";
  preprocessed = "{scratch}/source.i";
  seen = (if Str.endsWith ".s" source then source else
    _ = runCompiler (cc + ["-E",source,"-o",preprocessed]); preprocessed);
  key = objectKey version cc seen;
  base = K.baseName source; suffix = K.suffix source;
  stem = substr base 0 (Str.len base - Str.len suffix);
  object = "{cache}/{stem}-{key}.o";
  _ = (if K.exists object then Unit else
    partial = "{scratch}/object";
    _ = runCompiler (cc + ["-c",source,"-o",partial]);
    _ = K.need (Fs.copyPublishNow partial object 65536 True); Unit);
  print object.
> case args Unit of cache :: version :: source :: cc -> build cache version source cc
  | _ -> error "usage: ccobj-worker.sol CACHE VERSION_FILE SOURCE CC FLAGS...".
