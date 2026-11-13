K = use "sdk/sdk".
digits s = s != "" and List.all (fn c -> c >= 48 and c <= 57) (Str.codes s).
number s = if digits s then (case Try.parseInt s of Ok n -> n | Err _ -> -1) else -1.
# Read just the header page. Payloads may contain arbitrary binary data.
header source slot =
  dump = K.command ["od","-An","-v","-tu1","-j",str (slot * 4096),"-N","4096",source];
  codes = List.concat (List.map Str.words (Str.lines dump));
  text = Str.join "" (List.map (fn w -> n = number w; if n > 127 then "?" else Str.fromCode n) codes);
  Str.words (case Str.split 10 text of first :: _ -> first | [] -> "").
seal words = case words of
    "QLOG" :: head :: tags ->
      gens = List.filter (fn t -> Str.startsWith "g" t and digits (K.drop 1 t)) tags;
      gen = (case gens of first :: _ -> number (K.drop 1 first) | [] -> 0);
      if number head >= 0 then (gen,number head) else (-1,0)
  | _ -> (-1,0).
copyRecords : unsafe String -> String -> String -> List String -> Int -> Int -> Int -> Int -> Int .
copyRecords src dest scratch keys pos head target limit =
  if pos >= head then target else case header src pos of
    tag :: pages :: _ :: key :: _ ->
      n = number pages;
      if n < 0 or n >= head - pos or List.has tag ["QREC","QDEL","QBLK"] == False then target else
        skip = tag != "QBLK" and List.has key keys;
        next = (if skip then target else
          _ = K.check "preserved records exceed DATA partition" (n + 1 <= limit - target);
          _ = K.command ["dd","if={src}","of={dest}","bs=4096","skip={pos}","seek={target}","count={n + 1}","conv=notrunc"];
          target + n + 1);
        copyRecords src dest scratch keys (pos + n + 1) head next limit
  | _ -> target.
appendOld : unsafe String -> String -> String -> List String -> Int -> Int -> Int .
appendOld image dest scratch keys target limit =
  if K.exists image == False then target else
    src = "{scratch}/previous"; _ = K.copy image src;
    sizeWords = Str.words (K.command ["wc","-c",src]);
    size = (case sizeWords of first :: _ -> number first | _ -> -1);
    pages = size / 4096;
    if pages < 1 or size % 4096 != 0 then target else
      (g1,h1) = seal (header src 0); (g2,h2) = seal (header src (pages - 1));
      head = (if g2 > g1 then h2 else h1);
      if head <= 1 or head > pages then target else copyRecords src dest scratch keys 1 head target limit.
