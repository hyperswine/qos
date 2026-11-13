# ELF64 static symbol tables. Decode names only for symbols the caller selects.
readFile path =
  r = unwrap (Stream.openRead path 65536);
  (chunks,next) = Stream.foldChunks (fn xs b -> b :: xs) [] r;
  _ = unwrap (Stream.closeRead next);
  Bytes.concat (List.rev (unwrap chunks)).
number bytes little off width =
  part = Bytes.toList (unwrap (Bytes.slice off width bytes));
  List.fold (fn acc b -> acc * 256 + b) 0 (if little then List.rev part else part).
indices count = if count <= 0 then [] else List.range 0 (count - 1).
endName : unsafe Bytes -> Int -> Int .
endName table pos = if unwrap (Bytes.at pos table) == 0 then pos else endName table (pos + 1).
entries : unsafe Bytes -> Bool -> (Int -> Int -> Bool) -> Int -> Int -> Int -> List (String,Int,Int) .
entries bytes little accept headers stride section =
  n = number bytes little;
  if n (section + 4) 4 != 2 then [] else
    offset = n (section + 24) 8; size = n (section + 32) 8;
    link = headers + stride * n (section + 40) 4;
    strings = unwrap (Bytes.slice (n (link + 24) 8) (n (link + 32) 8) bytes);
    step = n (section + 56) 8;
    count = (if step < 24 then error "invalid ELF64 symbol stride" else size / step);
    offsets = List.map (fn i -> offset + i * step) (indices count);
    selected = List.filter (fn p -> accept (n (p + 4) 1 / 16) (n (p + 6) 2)) offsets;
    List.map (fn p -> start = n p 4; stop = endName strings start;
      name = unwrap (Utf8.decode (unwrap (Bytes.slice start (stop - start) strings)));
      (name,n (p + 8) 8,n (p + 16) 8)) selected.
symbols : unsafe Bytes -> (Int -> Int -> Bool) -> List (String,Int,Int) .
symbols bytes accept =
  magic = Bytes.toList (unwrap (Bytes.slice 0 5 bytes));
  encoding = unwrap (Bytes.at 5 bytes);
  little = (case encoding of 1 -> True | 2 -> False | _ -> error "invalid ELF byte order");
  n = number bytes little;
  headers = n 40 8; stride = n 58 2; count = n 60 2;
  if magic != [127,69,76,70,2] then error "expected ELF64"
  else if and (count > 0) (stride < 64) then error "invalid ELF64 section stride"
  else List.concat (List.map (fn i -> entries bytes little accept headers stride (headers + stride * i)) (indices count)).
