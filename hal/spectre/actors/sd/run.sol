# The SD storage actor on the board: sol run.sol storage.bin PORT
# Reads sector 131072, keeps a backup beside this run, WRITES a random test
# record there, reads it back before and after a CPU reset, and restores the
# original sector. The backup is spectre-sd-*/CID-131072.hex (the sector as hex).
unsafe program.
R = use "../rom-lib".
B = use "sol/lib/build".
K = use "../../../../tools/sdk/sdk".
between open close text = at = Str.indexOf open text;
  if at < 0 then error "missing {open} in {text}" else
    rest = Str.slice text (at + Str.len open) (Str.len text);
    end = Str.indexOf close rest;
    if end < 0 then error "unterminated {open}" else Str.slice rest 0 end.
ready text = R.ensure "the actor did not end at READY: {Str.slice text 0 150}" (Str.endsWith "READY\n" text).
# upload and start; answers the card's CID
start image port = out = R.uart port ["upload",image,"45","1","expect","READY\n","12"];
  _ = ready out; _ = print (Str.trim (Str.slice out 0 (Str.indexOf "\n" out)));
  cid = between "CID " "\n" out;
  _ = R.ensure "malformed CID" (Str.len cid == 32);
  cid.
readSector port = out = R.uart port ["send-hex","52","expect","READY\n","12"];
  _ = ready out;
  data = between "DATA " "\n" out;
  _ = R.ensure "a sector is 512 bytes" (Str.len data == 1024);
  data.
# 'W' and the sector as hex text
writeSector port data = out = R.uart port ["send-hex","57{hexOfText data}","expect","READY\n","12"];
  _ = ready out;
  R.ensure "the write was not acknowledged" (Str.contains "WROTE\n" out).
hexDigit n = Str.slice "0123456789abcdef" n (n + 1).
hexOfText text = Str.join "" (List.map (fn c -> "{hexDigit (c / 16)}{hexDigit (c % 16)}") (Str.codes text)).
> case args Unit of
    [image, port] ->
      here = B.query ["/bin/pwd","-P"];
      cid = start image port;
      original = readSector port;
      dir = Str.trim (K.command ["/usr/bin/mktemp","-d","{here}/spectre-sd-XXXXXX"]);
      path = "{dir}/{cid}-131072.hex";
      _ = K.writeText path original;
      _ = K.command ["/bin/sync"];
      record = "{hexOfText "QOS/Spectre reset test\n"}{Str.trim (K.command ["/usr/bin/openssl","rand","-hex","489"])}";
      _ = R.ensure "the test record is not a different sector" (Str.len record == 1024 and record != original);
      _ = print "Backup: {path} test SHA256: {K.sha256Text record}";
      _ = writeSector port record;
      _ = R.ensure "the record did not read back" (readSector port == record);
      _ = print "Write and immediate read OK; resetting CPU to ROM and reloading image";
      _ = R.ensure "another card answered after the reset" (start image port == cid);
      after = readSector port;
      _ = writeSector port original;
      _ = R.ensure "the original sector did not read back" (readSector port == original);
      _ = print "Original sector restored and verified";
      _ = R.ensure "the record did not survive the reset" (after == record);
      print "PASS: fresh actor read all 512 bytes after reset"
  | _ -> error "usage: sol run.sol storage.bin PORT".
