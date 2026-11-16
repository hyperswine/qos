# The VFS probe on the board: sol run.sol image.bin PORT --read-existing|--initialize-test-slice
# --initialize-test-slice WRITES the first filesystem slice of the SD card before reading it back.
unsafe program.
R = use "../rom-lib".
pass image port mode =
  out = R.uart port ["upload",image,"300","0","expect","MODE?\n","8","send-hex",(if mode == "W" then "57" else "52"),"expect","DONE","25"];
  _ = print "{mode}\n{out}";
  rows = Str.lines out;
  want = if mode == "W" then "SAVED " else "READ hello from Spectre";
  R.ensure "VFS acceptance failed ({mode})" (List.any (fn row -> row == want) rows and Str.endsWith "DONE" out).
> case args Unit of
    [image, port, "--read-existing"] -> pass image port "R"
  | [image, port, "--initialize-test-slice"] -> _ = pass image port "W"; pass image port "R"
  | _ -> error "usage: sol run.sol image.bin PORT --read-existing|--initialize-test-slice".
