# Flatten ELF64 PT_LOAD segments. File gaps are zero-filled; trailing BSS
# contributes to the memory extent only.
E = use "elf-symbols".
max a b = if a > b then a else b.
min a b = if a < b then a else b.
Segment = Type (Segment Int Int Int Int Int).
Image = Type (Image Int Int Int Int Bytes Int).
insert : unsafe Segment -> List Segment -> List Segment .
insert seg sorted = case sorted of
    [] -> [seg]
  | first :: rest -> Segment addr _ _ _ _ = seg; Segment next _ _ _ _ = first;
    if addr < next then seg :: sorted else first :: insert seg rest.
zeros : unsafe Int -> Bytes .
zeros n = if n == 0 then Bytes.empty Unit else if n == 1 then unwrap (Bytes.fromList [0]) else
  half = zeros (n / 2); Bytes.concat [half,half,zeros (n % 2)].
payload : unsafe Bytes -> Int -> List Segment -> List Bytes .
payload elf cursor segments = case segments of
    [] -> []
  | seg :: rest -> Segment addr offset size mem flags = seg;
    if size == 0 then payload elf cursor rest else
    if addr < cursor then error "overlapping ELF file segments" else
    zeros (addr - cursor) :: unwrap (Bytes.slice offset size elf) :: payload elf (addr + size) rest.
flatten : unsafe Bytes -> Image .
flatten elf =
  magic = Bytes.toList (unwrap (Bytes.slice 0 5 elf));
  little = (case unwrap (Bytes.at 5 elf) of 1 -> True | 2 -> False | _ -> error "invalid ELF encoding");
  n = E.number elf little; entry = n 24 8; headers = n 32 8; stride = n 54 2; count = n 56 2;
  _ = (if or (magic != [127,69,76,70,2]) (stride < 56) then error "invalid ELF64 program headers" else Unit);
  offsets = List.map (fn i -> headers + i * stride) (E.indices count);
  loads = List.filter (fn p -> and (n p 4 == 1) (n (p + 40) 8 != 0)) offsets;
  segments = List.map (fn p -> size = n (p + 32) 8; mem = n (p + 40) 8;
    if size > mem then error "ELF file segment exceeds memory size"
    else Segment (n (p + 16) 8) (n (p + 8) 8) size mem (n (p + 4) 4)) loads;
  sorted = List.fold (fn acc seg -> insert seg acc) [] segments;
  case sorted of
    [] -> error "ELF has no loadable segments"
  | first :: rest -> Segment base _ _ _ _ = first;
    limit = List.fold (fn high seg -> Segment addr _ _ mem _ = seg; max high (addr + mem)) base sorted;
    execEnd = List.fold (fn high seg -> Segment addr _ size _ flags = seg; if flags % 2 == 1 then max high (addr + size) else high) base sorted;
    writable = List.fold (fn low seg -> Segment addr _ _ _ flags = seg; if flags / 2 % 2 == 1 then min low addr else low) limit sorted;
    if or (entry < base) (entry >= limit) then error "ELF entry outside loadable span" else
    Image base (entry - base) (execEnd - base) (writable - base) (Bytes.concat (payload elf base sorted)) (limit - base).
