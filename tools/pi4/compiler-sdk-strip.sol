step what argv = case Proc.streamNow (ProcessSpec argv "" [] "" 0) of
    Ok 0 -> Unit | result -> error "{what} failed: {result}".
replace path =
  copy = "{path}.stripped";
  _ = step "stripping {path}" ["strip","--strip-unneeded","-o",copy,path];
  _ = step "keeping the mode of {path}" ["chmod","--reference={path}",copy];
  step "replacing {path}" ["mv","-f",copy,path].
# Inspect the four ELF magic bytes without loading toolchain binaries into memory.
stripFile path =
  reader = unwrap (Stream.openRead path 4);
  (chunk,next) = Stream.readChunk reader;
  _ = unwrap (Stream.closeRead next);
  case unwrap chunk of
    EndBytes -> Unit
  | ChunkBytes bytes -> if Bytes.toList bytes == [127,69,76,70] then
      # Strip a copy and rename it over the original: the packaging may be
      # running one of these binaries (bin/sol), and a running image cannot
      # be rewritten in place (ETXTBSY); a rename leaves its inode alone.
      replace path
    else Unit.
stripTree sdk =
  ProcessResult code paths err = unwrap (Proc.runNow (ProcessSpec ["find",sdk,"-type","f","-print0"] "" [] "" 0));
  if code != 0 then error "listing SDK files failed: {err}" else
    _ = List.map stripFile (List.filter (fn p -> p != "") (Str.split 0 paths)); Unit.
> case args Unit of [sdk] -> stripTree sdk | _ -> error "expected SDK_DIRECTORY".
