# Host-side helpers for the board hooks. Keep existing file modes when rewriting
# Buildroot outputs. Temporary siblings allow rename on the same filesystem.
setting key = case unwrap (Env.get key) of EnvText s -> s | EnvMissing -> "".
required key = value = setting key; if value == "" then error "missing {key}" else value.
run dir argv = status = unwrap (Proc.streamNow (ProcessSpec argv dir [] "" 0)); if status == 0 then Unit else error "{argv} exited {status}".
command argv = run "" argv.
exists flag path = ProcessResult code _ _ = unwrap (Proc.runNow (ProcessSpec ["test",flag,path] "" [] "" 0)); code == 0.
readText path =
  reader = unwrap (Stream.openRead path 65536);
  (result,next) = Stream.foldChunks (fn acc b -> b :: acc) [] reader;
  _ = unwrap (Stream.closeRead next);
  unwrap (Utf8.decode (Bytes.concat (List.rev (unwrap result)))).
rewrite path text =
  # mktemp produces a unique sibling. cp -p supplies the original file mode
  # and ownership before tee overwrites its contents.
  ProcessResult status out err = unwrap (Proc.runNow (ProcessSpec ["mktemp",path + ".XXXXXXXX"] "" [] "" 0));
  if status != 0 then error "cannot create temporary file for {path}: {err}" else
    tmp = substr out 0 (Str.len out - 1);
    copy = Proc.runNow (ProcessSpec ["cp","-p",path,tmp] "" [] "" 0);
    result = (case copy of Ok (ProcessResult 0 _ _) ->
      (case Proc.pipeline (PipelineSpec [ProcessSpec ["tee",tmp] "" [] "" 0] (PipeBytes (unwrap (Utf8.encode text))) PipeDiscard PipeOutputInherit 0 PipeFail) of
        Ok (PipelineResult 0 _ _ _) -> Proc.runNow (ProcessSpec ["mv","-f",tmp,path] "" [] "" 0)
      | _ -> Err "writing temporary file failed")
      | failed -> failed);
    case result of Ok (ProcessResult 0 _ _) -> Unit | failed -> _ = command ["rm","-f",tmp]; error "updating {path}: {failed}".
rows text = Str.split 10 text.
linesText lines = Str.join "" (List.map (fn line -> line + "\n") lines).
getty tty comment = "{tty}::respawn:/sbin/getty -L {tty} 0 linux # {comment}".
withConsole lines tty comment = linesText lines + (if List.any (Str.startsWith (tty + "::")) lines then "" else "\n" + getty tty comment + "\n").
