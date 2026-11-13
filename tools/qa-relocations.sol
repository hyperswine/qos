# QAR2 relocation offsets for ELF64 SHT_RELA sections targeting loaded memory.
E = use "elf-symbols".
rules machine = case machine of
    243 -> (2,[0,16,17,18,19,23,24,25,33,34,35,36,37,38,39,40,43,44,45,51,52,53,54,55,56,57])
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
rows n little policy base length symOff symSize symStep section =
  (absolute,free) = policy; start = n (section + 24) 8; size = n (section + 32) 8; step = n (section + 56) 8;
  _ = (if or (step < 24) (symStep < 24) then error "invalid relocation or symbol stride" else Unit);
  _ = (if size % step != 0 then error "partial ELF relocation" else Unit);
  List.fold (fn acc index ->
    pos = start + index * step; address = n pos 8;
    kind = n (pos + (if little then 8 else 12)) 4; sym = n (pos + (if little then 12 else 8)) 4;
    _ = (if sym >= symSize / symStep then error "invalid relocation symbol index" else Unit);
    defined = n (symOff + sym * symStep + 6) 2;
    if or (List.has kind free) (defined == 65521) then acc
    else if or (kind != absolute) (defined == 0) then error "unsupported relocation type {kind} at {address}"
    else offset = address - base;
      if or (offset < 0) (offset > length - 8) then error "relocated word outside image"
      else offset :: acc) [] (E.indices (size / step)).
offsets : unsafe Bytes -> Int -> Int -> List Int .
offsets bytes base length =
  little = (case unwrap (Bytes.at 5 bytes) of 1 -> True | 2 -> False | _ -> error "invalid ELF encoding");
  n = E.number bytes little; policy = rules (n 18 2);
  headers = n 40 8; stride = n 58 2; count = n 60 2;
  section = (fn i -> if i >= count then error "invalid ELF section index" else headers + stride * i);
  _ = (if and (count > 0) (stride < 64) then error "invalid section header stride" else Unit);
  parts = List.map (fn i -> s = section i;
    if n (s + 4) 4 != 4 then [] else target = section (n (s + 44) 4);
    if n (target + 8) 8 / 2 % 2 == 0 then [] else syms = section (n (s + 40) 4);
    rows n little policy base length (n (syms + 24) 8) (n (syms + 32) 8) (n (syms + 56) 8) s) (E.indices count);
  ordered (List.concat parts).
