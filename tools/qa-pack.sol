E = use "elf-symbols".
I = use "elf-image".
R = use "qa-relocations".
M = use "qa-moved".
Imports = use "qa-imports".
utf8 text = unwrap (Utf8.encode text).
digest bytes = Hex.encode (Sha256.bytes bytes).
machine elf = case E.number elf (unwrap (Bytes.at 5 elf) == 1) 18 2 of
    62 -> "x86_64" | 183 -> "aarch64" | 243 -> "riscv64" | other -> error "unsupported ELF machine {other}".
fields : unsafe List String -> List String .
fields lines = case lines of
    [] -> []
  | line :: rest -> if Str.startsWith "[" (Str.trim line) then [] else
      parts = Str.split 61 line;
      (case parts of key :: value -> if and (value != []) (Str.trim key == "architecture") then Str.trim (Str.join "=" value) :: fields rest else fields rest | [] -> fields rest).
manifest : unsafe String -> String -> String .
manifest text arch = quoted = "\"{arch}\""; case fields (Str.lines text) of
    [] -> "architecture = {quoted}\n" + text
  | [value] -> if value == quoted then text else error "manifest architecture differs from ELF"
  | _ -> error "multiple manifest architecture declarations".
offsetBytes n = if or (n < 0) (n > 4294967295) then error "relocation exceeds QAR2 offset range" else
  unwrap (Bytes.fromList [n % 256,n / 256 % 256,n / 65536 % 256,n / 16777216]).
archive sections =
  (total,lines) = List.fold (fn acc part -> (off,prev) = acc; (name,blob) = part; count = Bytes.len blob;
    (off + count,"{name} {off} {count}" :: prev)) (0,[]) sections;
  header = utf8 ("QAR2\n" + Str.join "\n" (List.rev lines) + "\n\n");
  Bytes.concat (header :: List.map (fn part -> (name,blob) = part; blob) sections).
need result = case result of Ok value -> value | Err why -> error "{why}".
writeChunks : unsafe Bytes -> Int -> ByteWriter -> ByteWriter .
writeChunks bytes off writer =
  if off == Bytes.len bytes then writer else
    size = I.min 65536 (Bytes.len bytes - off);
    (result,next) = Stream.writeChunk (unwrap (Bytes.slice off size bytes)) writer;
    _ = need result; writeChunks bytes (off + size) next.
publish : unsafe String -> Bytes -> Unit .
publish path bytes =
  scratch = tempDir "qa-pack"; file = "{scratch}/archive";
  writer = need (Stream.openWrite file 65536);
  _ = need (Stream.closeWrite (writeChunks bytes 0 writer));
  _ = need (Fs.copyPublishNow file path 65536 True); Unit.
abiVersion text =
  value = parseInt text;
  if and (value > 0) (value <= 999999999) then value else error "ABI version outside 1..999999999".
nativeFields versions = case versions of
    [native] -> "nativeabi {abiVersion native}\n"
  | [native,actors,memory] -> "nativeabi {abiVersion native}\nplaneactors {abiVersion actors}\nplanememory {abiVersion memory}\n"
  | _ -> error "expected a native ABI version and optionally two plane ABI versions".
loadHeader base entry execsz rw image mem =
  "base {base}\nentry {entry}\nexecsz {execsz}\nrwoff {rw}\nimagesz {Bytes.len image}\nmemsz {mem}\nsha {digest image}\n".
coreSections : unsafe String -> Bytes -> String -> Bytes -> List (String,Bytes) .
coreSections man elf load image =
  [("MANIFEST",utf8 (manifest (readPath man) (machine elf))),("LOAD",utf8 load),("IMAGE",image)].
fixed : unsafe String -> String -> String -> Unit .
fixed man input dest =
  elf = E.readFile input; I.Image base entry execsz rw image mem = I.flatten elf;
  publish dest (archive (coreSections man elf (loadHeader base entry execsz rw image mem) image)).
pack : unsafe String -> String -> String -> String -> Int -> Bool -> String -> Unit .
pack man input moved dest delta plugin abi =
  elf = E.readFile input; I.Image base entry execsz rw image mem = I.flatten elf;
  _ = (if base == 0 then Unit else error "relocatable image must be linked at zero");
  offsets = R.offsets elf base (Bytes.len image);
  _ = (if moved == "" then Unit else
    I.Image otherBase otherEntry otherExec otherRw otherImage otherMem = I.flatten (E.readFile moved);
    M.check image otherImage offsets delta);
  reloc = Bytes.concat (List.map offsetBytes offsets);
  imports = (if plugin then utf8 (Imports.section elf base) else Bytes.empty Unit);
  load = loadHeader base entry execsz rw image mem + abi + "relsha {digest (Bytes.concat [reloc,imports])}\n";
  sections = coreSections man elf load image + [("RELOC",reloc)];
  publish dest (archive (sections + (if plugin then [("IMPORT",imports)] else []))).
main : unsafe Unit -> Unit .
> case args Unit of ["fixed",man,input,dest] -> fixed man input dest
  | [mode,man,input,moved,delta,dest] ->
    if List.has mode ["plugin","process"] then pack man input moved dest (parseInt delta) (mode == "plugin") "" else error "unknown archive mode {mode}"
  | mode :: man :: input :: moved :: delta :: dest :: versions ->
    if List.has mode ["native","native-plugin"] then pack man input moved dest (parseInt delta) (mode == "native-plugin") (nativeFields versions)
    else error "unknown archive mode {mode}"
  | _ -> error "usage: qa-pack.sol process|plugin|native MANIFEST ELF MOVED_ELF DELTA OUTPUT [NATIVE_ABI [ACTORS_ABI MEMORY_ABI]]".
