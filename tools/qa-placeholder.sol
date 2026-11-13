# Native fallback registry entries carry a TOML manifest and an empty image.
pack manifestPath archive =
  manifest = readPath manifestPath;
  manifestSize = Bytes.len (unwrap (Utf8.encode manifest));
  digest = Hex.encode (Sha256.bytes (unwrap (Utf8.encode "")));
  load = "base 0\nentry 0\nexecsz 0\nrwoff 0\nimagesz 0\nmemsz 0\nsha {digest}\n";
  loadSize = Bytes.len (unwrap (Utf8.encode load));
  imageOffset = manifestSize + loadSize;
  header = "QAR2\nMANIFEST 0 {manifestSize}\nLOAD {manifestSize} {loadSize}\nIMAGE {imageOffset} 0\n\n";
  writePath archive (header + manifest + load).
> case args Unit of [manifest,archive] -> pack manifest archive
  | _ -> error "usage: qa-placeholder.sol MANIFEST ARCHIVE".
