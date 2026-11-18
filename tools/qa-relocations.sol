# QAR2 relocation offsets for ELF64 or ELF32 SHT_RELA sections targeting
# loaded memory. A relocated word is the image's word size (8 or 4 bytes).
E = use "elf-symbols".
rules machine wide = case machine of
    243 -> (if wide then 2 else 1,[0,16,17,18,19,23,24,25,33,34,35,36,37,38,39,40,43,44,45,51,52,53,54,55,56,57])
  | 183 -> (257,[0,260,261,262,273,274,275,276,277,278,284,285,286,299,279,280,282,283])
  | 62 -> (1,[0,2,4,24])
  | _ -> error "unsupported ELF relocation machine {machine}".
# Merge sorted offsets, coalescing duplicate references to the same word.
merge : unsafe List Int -> List Int -> List Int .
merge left right = case (left,right) of
    ([],_) -> right
  | (_,[]) -> left
  | (x :: xs,y :: ys) -> if x < y then x :: merge xs right else if y < x then y :: merge left ys else x :: merge xs ys.
ordered : unsafe List Int -> List Int .
ordered xs = case xs of [] -> [] | [x] -> [x] | _ ->
  half = List.len xs / 2; merge (ordered (List.take half xs)) (ordered (List.drop half xs)).
rows n little wide policy base length symOff symSize symStep section =
  (absolute,free) = policy;
  word = (if wide then 8 else 4);
  start = n (section + (if wide then 24 else 16)) word; size = n (section + (if wide then 32 else 20)) word;
  step = n (section + (if wide then 56 else 36)) word;
  _ = (if or (step < 3 * word) (symStep < (if wide then 24 else 16)) then error "invalid relocation or symbol stride" else Unit);
  _ = (if size % step != 0 then error "partial ELF relocation" else Unit);
  List.fold (fn acc index ->
    pos = start + index * step; address = n pos word;
    info = n (pos + word) word;
    (kind, sym) = (if wide then (n (pos + (if little then 8 else 12)) 4, n (pos + (if little then 12 else 8)) 4)
                   else (info % 256, info / 256));
    _ = (if sym >= symSize / symStep then error "invalid relocation symbol index" else Unit);
    defined = n (symOff + sym * symStep + (if wide then 6 else 14)) 2;
    if or (List.has kind free) (defined == 65521) then acc
    else if or (kind != absolute) (defined == 0) then error "unsupported relocation type {kind} at {address}"
    else offset = address - base;
      if or (offset < 0) (offset > length - word) then error "relocated word outside image"
      else offset :: acc) [] (E.indices (size / step)).
offsets : unsafe Bytes -> Int -> Int -> List Int .
offsets bytes base length =
  little = (case unwrap (Bytes.at 5 bytes) of 1 -> True | 2 -> False | _ -> error "invalid ELF encoding");
  wide = (case unwrap (Bytes.at 4 bytes) of 2 -> True | 1 -> False | _ -> error "invalid ELF class");
  word = (if wide then 8 else 4);
  n = E.number bytes little; policy = rules (n 18 2) wide;
  (headers, stride, count) = (if wide then (n 40 8, n 58 2, n 60 2) else (n 32 4, n 46 2, n 48 2));
  section = (fn i -> if i >= count then error "invalid ELF section index" else headers + stride * i);
  _ = (if and (count > 0) (stride < (if wide then 64 else 40)) then error "invalid section header stride" else Unit);
  # section header fields: link, info, flags, offset, size, entsize
  link = (fn s -> n (s + (if wide then 40 else 24)) 4); info = (fn s -> n (s + (if wide then 44 else 28)) 4);
  parts = List.map (fn i -> s = section i;
    if n (s + 4) 4 != 4 then [] else target = section (info s);
    if n (target + 8) word / 2 % 2 == 0 then [] else syms = section (link s);
    rows n little wide policy base length (n (syms + (if wide then 24 else 16)) word) (n (syms + (if wide then 32 else 20)) word)
      (n (syms + (if wide then 56 else 36)) word) s) (E.indices count);
  ordered (List.concat parts).
