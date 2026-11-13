P = use "qlog-preserve".
K = use "sdk/sdk".
appId path = base = K.baseName path; suffix = K.suffix base;
  stem = Str.slice base 0 (Str.len base - Str.len suffix);
  if stem == "" or List.all (fn c -> c == 46) (Str.codes stem) then base else stem.
summarize (size,hash) chunk = (size + Bytes.len chunk,
  List.fold (fn h byte -> (h * 31 + byte) % 1000000007) hash (Bytes.toList chunk)).
writeAt disk pos source = K.command ["dd","if={source}","of={disk}","bs=4096","seek={pos}","conv=notrunc"].
appendRecord scratch disk limit pos (url,path) =
  # Hash and write the same private copy even if the input changes during the build.
  payload = "{scratch}/payload"; _ = K.copy path payload;
  reader = K.need (Stream.openRead payload 4096);
  (result,next) = Stream.foldChunks summarize (0,7) reader;
  _ = K.need (Stream.closeRead next); (size,rawHash) = K.need result;
  hash = (if rawHash == 0 then 1 else rawHash);
  pages = (size + 4095) / 4096; end = pos + 1 + pages;
  _ = K.check "seed exceeds DATA partition" (end <= limit);
  header = "{scratch}/header";
  _ = K.writeText header "QREC {pages} {size} {url} h{hash}\n";
  _ = writeAt disk pos header; _ = writeAt disk (pos + 1) payload;
  end.
addKey keys entry =
  (url,_) = entry;
  _ = K.check "invalid record URL" (url != "" and Str.len url <= 3996 and List.all (fn c -> c > 32 and c < 127) (Str.codes url));
  _ = K.check "duplicate seed record URL: {url}" (List.has url keys == False);
  url :: keys.
freshDisk : unsafe String -> Int -> List String -> List (String,String) -> Bool -> Unit .
freshDisk image mib apps extra preserve =
  pages = mib * 256; limit = pages - pages / 8;
  scratch = tempDir "qlog-seed"; disk = "{scratch}/disk"; index = "{scratch}/index";
  _ = K.check "disk size must be positive" (mib > 0);
  _ = K.command ["dd","if=/dev/zero","of={disk}","bs=4096","count=0","seek={pages}"];
  ids = List.map appId apps; records = List.map (fn path -> ("apps/{appId path}.qa",path)) apps;
  _ = K.writeText index (Str.join "\n" ids + "\n");
  keys = List.fold addKey ("apps/index" :: List.map (fn id -> "apps/{id}.qa") ids) extra;
  capacity = (if extra == [] then limit else limit - 1);
  seeded = List.fold (appendRecord scratch disk capacity) 1 (records + [("apps/index",index)] + extra);
  head = (if preserve then P.appendOld image disk scratch keys seeded capacity else seeded);
  header = "{scratch}/header"; _ = K.writeText header "QLOG {head} v2 w0 c1 d{limit} s{limit} m0\n";
  _ = writeAt disk 0 header;
  _ = K.need (Fs.copyPublishNow disk image 65536 True);
  names = Str.join ", " ids; count = List.len ids;
  print "mkdisk: {image} seeded with {count} apps [{names}] + apps/index (head={head}, data-end={limit}/{pages})".
