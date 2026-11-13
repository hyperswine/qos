# QAR2 IMPORT records are named by the marker symbols in the final link.
E = use "elf-symbols".
Sort = use "sdk/sort".
prefix = "__qosimp_".
isMarker row = (name,value,size) = row; Str.startsWith prefix name.
decode base row =
  (name,value,size) = row;
  tag = substr name (Str.len prefix) (Str.len name);
  split = Str.indexOf "_" tag;
  kind = substr tag 0 split; symbol = substr tag (split + 1) (Str.len tag);
  off = value - base;
  if or (split < 1) (symbol == "") then error "invalid import marker {name}"
  else if kind == "c" then (symbol,"c {off} 8 {symbol}\n")
  else digits = substr kind 1 (Str.len kind);
    if and (Str.startsWith "d" kind) (and (digits != "") (List.all (fn c -> and (c >= 48) (c <= 57)) (Str.codes digits)))
    then (symbol,"d {off} {parseInt digits} {symbol}\n")
    else error "unknown import marker {name}".
distinct : unsafe List (String,String) -> List String .
distinct rows = case rows of
    a :: b :: rest -> (name,line) = a; (next,other) = b;
      if line == other then distinct (b :: rest) else line :: distinct (b :: rest)
  | [(name,line)] -> [line]
  | [] -> [].
section : unsafe Bytes -> Int -> String .
section bytes base =
  defined = E.symbols bytes (fn bind index -> index != 0);
  records = List.map (decode base) (List.filter isMarker defined);
  # Group exact duplicates within each symbol, including multiple slots for one name.
  byLine = Sort.sortBy (fn pair -> (name,line) = pair; line) records;
  Str.join "" (distinct (Sort.sortBy (fn pair -> (name,line) = pair; name) byLine)).
