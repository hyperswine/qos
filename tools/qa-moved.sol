# Check the unchanged spans and every relocated little-endian word (8 bytes
# for an ELF64 image, 4 for ELF32).
# Compare the two halves separately so unsigned words never overflow Sol Int.
E = use "elf-symbols".
sameSpan image moved start stop =
  length = stop - start;
  if length == 0 then Unit else
    if unwrap (Bytes.slice start length image) == unwrap (Bytes.slice start length moved) then Unit
    else error "unrelocated bytes differ in [{start},{stop})".
wordDelta image moved offset delta word = if word == 4 then
    d = E.number moved True offset 4 - E.number image True offset 4;
    want = delta % 4294967296;
    if (d + 4294967296) % 4294967296 == want then Unit else error "relocated word at offset {offset} did not move by {delta}"
  else
  radix = 4294967296;
  low = E.number moved True offset 4 - E.number image True offset 4;
  high = E.number moved True (offset + 4) 4 - E.number image True (offset + 4) 4;
  # Normalize signed remainders to a low word and carry.
  negative = delta % radix;
  rem = (if negative < 0 then negative + radix else negative);
  quot = delta / radix - (if negative < 0 then 1 else 0);
  carry = (if low < 0 then 1 else 0);
  if and (low + carry * radix == rem) (high - carry == quot) then Unit
  else error "relocated word at offset {offset} did not move by {delta}".
check image moved offsets delta word =
  length = Bytes.len image;
  _ = (if Bytes.len moved != length then error "moved image size differs" else Unit);
  cursor = List.fold (fn start offset ->
    _ = (if or (offset < start) (offset > length - word) then error "invalid relocation offset {offset}" else Unit);
    _ = sameSpan image moved start offset;
    _ = wordDelta image moved offset delta word;
    offset + word) 0 offsets;
  sameSpan image moved cursor length.
